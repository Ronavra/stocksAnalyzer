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

def facts_by_period(data: dict, years: int = 10):
    facts = (data.get("facts") or {}).get("us-gaap") or {}
    aliases = {
        "revenue": [
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
            "ShortTermBorrowings",
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
        for tag in aliases[key]:
            node = facts.get(tag) or {}
            for unit in units.get(key, ["USD"]):
                for x in (node.get("units") or {}).get(unit) or []:
                    if (
                        x.get("form") in ("10-K", "10-K/A")
                        and x.get("fp") == "FY"
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
                        found.append(x)
            if found:
                break
        return found

    out = {}
    for key in aliases:
        for x in rows_for(key):
            d = x["end"]
            rec = out.setdefault(d, {"period_end": d})
            marker = "_filed_" + key
            if (x.get("filed") or "") >= rec.get(marker, ""):
                rec[key] = x["val"]
                rec[marker] = x.get("filed") or ""
                rec["filed_date"] = max(rec.get("filed_date") or "", x.get("filed") or "")
                if x.get("accn"):
                    rec["accn"] = x["accn"]

    for rec in out.values():
        if rec.get("debt_total") is not None:
            rec["total_debt"] = rec["debt_total"]
        elif rec.get("debt_current") is not None or rec.get("debt_noncurrent") is not None:
            rec["total_debt"] = float(rec.get("debt_current") or 0) + float(rec.get("debt_noncurrent") or 0)
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

    Duration facts are restricted to roughly one quarter (60-120 days), which
    avoids accidentally storing year-to-date 10-Q values as single-quarter data.
    """
    facts = (data.get("facts") or {}).get("us-gaap") or {}
    aliases = {
        "revenue": [
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
            "ShortTermBorrowings",
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
        for tag in aliases[key]:
            node = facts.get(tag) or {}
            for unit in units.get(key, ["USD"]):
                for x in (node.get("units") or {}).get(unit) or []:
                    if (
                        x.get("form") in ("10-Q", "10-Q/A")
                        and x.get("fp") in ("Q1", "Q2", "Q3")
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
                        found.append(x)
            if found:
                break
        return found

    out = {}
    for key in aliases:
        for x in rows_for(key):
            d = x["end"]
            rec = out.setdefault(d, {"period_end": d})
            marker = "_filed_" + key
            if (x.get("filed") or "") >= rec.get(marker, ""):
                rec[key] = x["val"]
                rec[marker] = x.get("filed") or ""
                rec["filed_date"] = max(rec.get("filed_date") or "", x.get("filed") or "")
                if x.get("accn"):
                    rec["accn"] = x["accn"]

    for rec in out.values():
        if rec.get("debt_total") is not None:
            rec["total_debt"] = rec["debt_total"]
        elif rec.get("debt_current") is not None or rec.get("debt_noncurrent") is not None:
            rec["total_debt"] = float(rec.get("debt_current") or 0) + float(rec.get("debt_noncurrent") or 0)
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
