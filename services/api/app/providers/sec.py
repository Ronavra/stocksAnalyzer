import os
from datetime import datetime, timezone
import httpx
from .base import ProviderValue, Provenance

class SECProvider:
    BASE_URL="https://data.sec.gov"
    def __init__(self,user_agent:str|None=None):
        self.user_agent=user_agent or os.getenv("SEC_USER_AGENT","StocksAnalyzer research-app contact@example.com")
    async def ticker_map(self)->dict:
        url="https://www.sec.gov/files/company_tickers.json"
        async with httpx.AsyncClient(timeout=30,headers={"User-Agent":self.user_agent}) as client:
            r=await client.get(url)
            if r.status_code in (403,429):
                raise RuntimeError(
                    f"SEC ticker map access limited (HTTP {r.status_code}); "
                    "verify SEC_USER_AGENT identifies the organization and a monitored contact email; "
                    "if access remains denied, check the runner IP with SEC webmaster"
                )
            if r.is_error: raise RuntimeError(f"SEC ticker map failed with HTTP {r.status_code}")
            data=r.json()
            return {str(v.get("ticker","")).upper().replace(".","-"):str(v.get("cik_str","")) for v in data.values()}

    async def company_facts(self,cik:str|int)->ProviderValue:
        cik10=str(cik).replace("CIK","").zfill(10)
        url=f"{self.BASE_URL}/api/xbrl/companyfacts/CIK{cik10}.json"
        async with httpx.AsyncClient(timeout=30,headers={"User-Agent":self.user_agent,"Accept-Encoding":"gzip, deflate"}) as client:
            r=await client.get(url)
            if r.status_code in (403,429): raise RuntimeError(f"SEC access limited (HTTP {r.status_code}); check SEC_USER_AGENT and request rate")
            if r.is_error: raise RuntimeError(f"SEC companyfacts failed with HTTP {r.status_code}")
            return ProviderValue(r.json(),Provenance("sec",url,datetime.now(timezone.utc)))

    async def submissions(self,cik:str|int)->dict:
        cik10=str(cik).replace("CIK","").zfill(10)
        url=f"{self.BASE_URL}/submissions/CIK{cik10}.json"
        async with httpx.AsyncClient(timeout=30,headers={"User-Agent":self.user_agent}) as client:
            r=await client.get(url)
            if r.is_error:
                raise RuntimeError(f"SEC submissions failed with HTTP {r.status_code}")
            return r.json()


def latest_financial_report(submissions:dict):
    """A successful facts download is checked against the actual filings list."""
    recent=((submissions.get("filings") or {}).get("recent") or {})
    result=[]
    for index,form in enumerate(recent.get("form") or []):
        if form not in ("10-K","10-K/A","10-Q","10-Q/A","20-F","20-F/A","40-F","40-F/A"):
            continue
        def value(key):
            values=recent.get(key) or []
            return values[index] if index<len(values) else None
        period=value("reportDate")
        if period:
            result.append({"period_end":period,"filed_date":value("filingDate"),"form":form})
    return max(result,key=lambda r:(r["period_end"],r["filed_date"] or "")) if result else None


def _fact_priority(filed,alias_index,tag,key):
    # For banks, contract revenue can cover fees alone. Prefer explicitly
    # reported total revenue net of interest when available for that period.
    bank_total=key=="revenue" and tag=="RevenuesNetOfInterestExpense"
    return (bank_total,filed or "",-alias_index)

def facts_by_period(data: dict, years: int = 10):
    facts = (data.get("facts") or {}).get("us-gaap") or {}
    aliases = {
        "revenue": [
            "RevenuesNetOfInterestExpense",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "SalesRevenueGoodsNet",
        ],
        "operating_income": ["OperatingIncomeLoss"],
        "net_income": ["NetIncomeLoss", "ProfitLoss"],
        "eps_diluted": ["EarningsPerShareDiluted"],
        "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
        "capex": [
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsForAdditionsToPropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets",
        ],
        "cash": [
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ],
        "debt_current": [
            "LongTermDebtAndFinanceLeaseObligationsCurrent",
            "LongTermDebtCurrent",
        ],
        "debt_noncurrent": [
            "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
            "LongTermDebtNoncurrent",
        ],
        "debt_total": ["LongTermDebtAndFinanceLeaseObligations", "LongTermDebt"],
    }
    units = {"eps_diluted": ["USD/shares"]}
    duration_keys = {"revenue", "operating_income", "net_income", "eps_diluted", "operating_cash_flow", "capex"}

    def rows_for(key):
        found = []
        for alias_index,tag in enumerate(aliases[key]):
            node = facts.get(tag) or {}
            for unit in units.get(key, ["USD"]):
                for x in (node.get("units") or {}).get(unit) or []:
                    if (
                        x.get("form") in ("10-K", "10-K/A","20-F","20-F/A","40-F","40-F/A")
                        and x.get("end")
                        and x.get("val") is not None
                    ):
                        if key in duration_keys:
                            start = x.get("start")
                            if not start:
                                continue
                            try:
                                days = (datetime.fromisoformat(x["end"]) - datetime.fromisoformat(start)).days
                            except ValueError:
                                continue
                            if not 300 <= days <= 430:
                                continue
                        found.append({**x,"_priority":_fact_priority(x.get("filed"),alias_index,tag,key)})
        return found

    out = {}
    for key in aliases:
        for x in rows_for(key):
            d = x["end"]
            rec = out.setdefault(d, {"period_end": d})
            marker = "_filed_" + key
            if x["_priority"] >= rec.get(marker, (False,"",-999)):
                rec[key] = x["val"]
                rec[marker] = x["_priority"]
                rec["filed_date"] = max(rec.get("filed_date") or "", x.get("filed") or "")
                if x.get("accn"):
                    rec["accn"] = x["accn"]

    for rec in out.values():
        if rec.get("debt_total") is not None:
            rec["total_debt"] = rec["debt_total"]
        elif rec.get("debt_current") is not None and rec.get("debt_noncurrent") is not None:
            rec["total_debt"] = float(rec["debt_current"]) + float(rec["debt_noncurrent"])
        ocf, capex = rec.get("operating_cash_flow"), rec.get("capex")
        rec["free_cash_flow"] = None if ocf is None or capex is None else float(ocf) - abs(float(capex))
        for k in list(rec):
            if k.startswith("_filed_") or k in ("debt_current", "debt_noncurrent", "debt_total"):
                rec.pop(k, None)

    # Keep only real fiscal-year records with enough core data to be useful.
    annual = [
        rec for rec in out.values()
        if sum(rec.get(k) is not None for k in ("revenue", "operating_income", "net_income", "eps_diluted")) >= 2
    ]
    return sorted(annual, key=lambda x: x["period_end"], reverse=True)[:years]


def quarter_facts_by_period(data: dict, quarters: int = 16):
    """Extract discrete 10-Q quarter facts plus quarter-end balance-sheet values.

    Most duration facts are reported for one quarter (60-120 days). Cash-flow
    facts are commonly year-to-date, so derive Q2/Q3 by subtracting the
    preceding cumulative filing from the same fiscal year.
    """
    facts = (data.get("facts") or {}).get("us-gaap") or {}
    aliases = {
        "revenue": [
            "RevenuesNetOfInterestExpense",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "SalesRevenueGoodsNet",
        ],
        "operating_income": ["OperatingIncomeLoss"],
        "net_income": ["NetIncomeLoss", "ProfitLoss"],
        "eps_diluted": ["EarningsPerShareDiluted"],
        "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
        "capex": [
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsForAdditionsToPropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets",
        ],
        "cash": [
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ],
        "debt_current": [
            "LongTermDebtAndFinanceLeaseObligationsCurrent",
            "LongTermDebtCurrent",
        ],
        "debt_noncurrent": [
            "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
            "LongTermDebtNoncurrent",
        ],
        "debt_total": ["LongTermDebtAndFinanceLeaseObligations", "LongTermDebt"],
    }
    units = {"eps_diluted": ["USD/shares"]}
    duration_keys = {"revenue", "operating_income", "net_income", "eps_diluted", "operating_cash_flow", "capex"}

    def rows_for(key):
        found = []
        for alias_index,tag in enumerate(aliases[key]):
            node = facts.get(tag) or {}
            for unit in units.get(key, ["USD"]):
                for x in (node.get("units") or {}).get(unit) or []:
                    if (
                        x.get("form") in ("10-Q", "10-Q/A","10-K","10-K/A")
                        and x.get("end")
                        and x.get("val") is not None
                    ):
                        if key in duration_keys:
                            start = x.get("start")
                            if not start:
                                continue
                            try:
                                days = (datetime.fromisoformat(x["end"]) - datetime.fromisoformat(start)).days
                            except ValueError:
                                continue
                            if not 60 <= days <= 120:
                                continue
                        found.append({**x,"_priority":_fact_priority(x.get("filed"),alias_index,tag,key)})
        return found

    out = {}
    for key in aliases:
        for x in rows_for(key):
            d = x["end"]
            rec = out.setdefault(d, {"period_end": d})
            marker = "_filed_" + key
            if x["_priority"] >= rec.get(marker, (False,"",-999)):
                rec[key] = x["val"]
                rec[marker] = x["_priority"]
                rec["filed_date"] = max(rec.get("filed_date") or "", x.get("filed") or "")
                if x.get("accn"):
                    rec["accn"] = x["accn"]

    for key in ("operating_cash_flow", "capex"):
        # A 10-Q cash-flow statement usually contains Q1, first-half, and
        # nine-month totals. Never store Q2/Q3 cumulative totals as quarters.
        direct_ends={end for end,rec in out.items() if rec.get(key) is not None}
        for alias_index,tag in enumerate(aliases[key]):
            cumulative=[]
            for x in ((facts.get(tag) or {}).get("units") or {}).get("USD") or []:
                if (x.get("form") not in ("10-Q", "10-Q/A","10-K","10-K/A")
                    or not x.get("start") or not x.get("end")
                    or not x.get("filed") or x.get("val") is None):
                    continue
                try:
                    days=(datetime.fromisoformat(x["end"])-datetime.fromisoformat(x["start"])).days
                except ValueError:
                    continue
                if 60<=days<=310:
                    cumulative.append(x)
            if not cumulative:
                continue
            for current in cumulative:
                days=(datetime.fromisoformat(current["end"])-datetime.fromisoformat(current["start"])).days
                if days<130:
                    continue
                previous=[x for x in cumulative
                          if x["start"]==current["start"]
                          and x["end"]<current["end"] and x["filed"]<=current["filed"]
                          and 60<=(datetime.fromisoformat(current["end"])-datetime.fromisoformat(x["end"])).days<=120]
                if not previous:
                    continue
                prior=max(previous,key=lambda x:(x["end"],x["filed"]))
                rec=out.setdefault(current["end"],{"period_end":current["end"]})
                marker="_filed_"+key
                # Prefer an explicitly reported single-quarter amount, if any.
                priority=_fact_priority(current["filed"],alias_index,tag,key)
                if current["end"] not in direct_ends and priority>=rec.get(marker,(False,"",-999)):
                    rec[key]=float(current["val"])-float(prior["val"])
                    rec[marker]=priority
                    rec["filed_date"]=max(rec.get("filed_date") or "",current["filed"])
                    if current.get("accn"):
                        rec["accn"]=current["accn"]

    for rec in out.values():
        if rec.get("debt_total") is not None:
            rec["total_debt"] = rec["debt_total"]
        elif rec.get("debt_current") is not None and rec.get("debt_noncurrent") is not None:
            rec["total_debt"] = float(rec["debt_current"]) + float(rec["debt_noncurrent"])
        ocf, capex = rec.get("operating_cash_flow"), rec.get("capex")
        rec["free_cash_flow"] = None if ocf is None or capex is None else float(ocf) - abs(float(capex))
        for k in list(rec):
            if k.startswith("_filed_") or k in ("debt_current", "debt_noncurrent", "debt_total"):
                rec.pop(k, None)

    quarterly = [
        rec for rec in out.values()
        if sum(rec.get(k) is not None for k in ("revenue", "operating_income", "net_income", "eps_diluted")) >= 2
    ]
    return sorted(quarterly, key=lambda x: x["period_end"], reverse=True)[:quarters]


def shares_outstanding_by_period(data: dict, max_points: int = 40):
    """Return latest filed common shares outstanding keyed by balance-sheet date."""
    facts = data.get("facts") or {}
    candidates = []
    for namespace, tag in (
        ("dei", "EntityCommonStockSharesOutstanding"),
        ("us-gaap", "CommonStockSharesOutstanding"),
    ):
        node = ((facts.get(namespace) or {}).get(tag) or {})
        for x in (node.get("units") or {}).get("shares") or []:
            if (
                x.get("form") in ("10-Q","10-Q/A","10-K","10-K/A")
                and x.get("end")
                and x.get("val") is not None
            ):
                candidates.append(x)
    out={}
    for x in candidates:
        d=x["end"]
        if d not in out or (x.get("filed") or "") >= (out[d].get("filed") or ""):
            out[d]={
                "shares_outstanding":x["val"],
                "filed":x.get("filed"),
                "accn":x.get("accn"),
            }
    return dict(sorted(out.items(),reverse=True)[:max_points])
