import os
import re
import math
import xml.etree.ElementTree as ET
import json
from pathlib import Path
from datetime import datetime, timezone
import httpx
from .base import ProviderValue, Provenance
from .sec_supplemental import CAPITAL_TAGS

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

    async def submission_history(self,cik,submissions,lookback_days,observed_at,max_files=30):
        """Follow the issuer's own older SEC inventory, preserving original filing dates."""
        from datetime import timedelta
        cik10=str(int(cik)).zfill(10)
        if str(submissions.get('cik','')).lstrip('0')!=str(int(cik)):
            raise ValueError('Historical filing issuer identity mismatch')
        cutoff=(datetime.fromisoformat(observed_at.replace('Z','+00:00'))-timedelta(days=lookback_days)).date().isoformat()
        files=[f for f in (submissions.get('filings') or {}).get('files',[]) if f.get('filingTo','')>=cutoff and f.get('filingFrom','')<=observed_at[:10]]
        if len(files)>max_files:raise ValueError('Historical SEC inventory exceeds bounded file limit')
        merged={k:list(v) for k,v in ((submissions.get('filings') or {}).get('recent') or {}).items()}
        async with httpx.AsyncClient(timeout=60,headers={'User-Agent':self.user_agent}) as client:
            for f in files:
                name=f.get('name','')
                if not re.fullmatch(r'CIK'+cik10+r'-submissions-\d{3}\.json',name):
                    raise ValueError('Unexpected historical SEC inventory filename')
                response=await client.get(self.BASE_URL+'/submissions/'+name);response.raise_for_status()
                old=response.json()
                if not isinstance(old.get('accessionNumber'),list):raise ValueError('Invalid historical SEC inventory')
                keys=set(merged)|set(old);prior_len=len(merged.get('accessionNumber',[]));old_len=len(old['accessionNumber'])
                for key in keys:
                    if not isinstance(old.get(key,[]),list):continue
                    merged.setdefault(key,['']*prior_len).extend(old.get(key) or ['']*old_len)
                import asyncio
                await asyncio.sleep(.2)
        return {**submissions,'filings':{'recent':merged,'files':[]}}

    async def filing_facts(self,cik,report):
        """Read the official XBRL instance when Company Facts lags a filing."""
        accession=report.get("accession_number") or ""
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}",accession):
            raise RuntimeError("Latest filing has no valid accession number")
        directory=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-','')}"
        async with httpx.AsyncClient(timeout=60,headers={"User-Agent":self.user_agent}) as client:
            listing=await client.get(directory+"/index.json")
            listing.raise_for_status()
            names=[x.get("name","") for x in listing.json().get("directory",{}).get("item",[])]
            instances=[name for name in names if re.fullmatch(r"[\w.-]+_htm.xml",name)]
            if len(instances)!=1:
                raise RuntimeError(f"Expected one extracted XBRL instance, found {len(instances)}")
            result=await client.get(directory+"/"+instances[0])
            result.raise_for_status()
            return instance_company_facts(result.content,cik,report)


def financial_reports(submissions:dict):
    """A successful facts download is checked against the actual filings list."""
    recent=((submissions.get("filings") or {}).get("recent") or {})
    result=[]
    reviews=json.loads((Path(__file__).resolve().parents[2]/'config'/'filing_reviews.json').read_text())
    for index,form in enumerate(recent.get("form") or []):
        if form not in ("10-K","10-K/A","10-Q","10-Q/A","20-F","20-F/A","40-F","40-F/A"):
            continue
        def value(key):
            values=recent.get(key) or []
            return values[index] if index<len(values) else None
        period=value("reportDate")
        if period:
            item={"period_end":period,"filed_date":value("filingDate"),"form":form}
            if value("accessionNumber"):
                item["accession_number"]=value("accessionNumber")
                review=reviews.get(item['accession_number'])
                if (review and str(submissions.get('cik','')).lstrip('0')==review['cik']
                    and item['period_end']==review['period_end'] and item['filed_date']==review['filed_date'] and form.endswith('/A')):
                    item['financial_statement_base_filed_date']=review['financial_statement_base_filed_date']
                    item['amendment_review']=review
            result.append(item)
    return sorted(result,key=lambda r:(r["period_end"],r["filed_date"] or ""),reverse=True)


def latest_financial_report(submissions:dict):
    reports=financial_reports(submissions)
    return reports[0] if reports else None


def instance_company_facts(xml,cik,report):
    """Convert consolidated, matching-entity standard XBRL facts to API shape.

    Segmented, other-entity and custom facts are deliberately excluded rather
    than guessing which business or share class they describe.
    """
    root=ET.fromstring(xml)
    ns={"x":"http://www.xbrl.org/2003/instance"}
    contexts={}; units={}
    for context in root.findall("x:context",ns):
        identifier=context.find("x:entity/x:identifier",ns)
        if identifier is None or (identifier.text or "").lstrip("0")!=str(int(cik)):
            continue
        members=[(el.attrib.get("dimension", ""), el.text or "") for el in context.iter() if el.tag.endswith("}explicitMember")]
        segmented=any(el.tag.endswith(("}segment","}scenario")) for el in context.iter())
        # Capital calculation approach is not a business segment. Accept only
        # the Standardized approach and never a subsidiary or other dimension.
        capital_only=bool(members) and not any(el.tag.endswith('}typedMember') for el in context.iter()) and all(
            (axis.split(':')[-1] in ('CapitalAdequacyApproachAxis','RiskWeightedAssetsCalculationMethodologyAxis') and member.split(':')[-1] in ('StandardizedApproachMember','BaselIIIStandardizedMember'))
            or (axis.split(':')[-1]=='ConsolidatedEntitiesAxis' and member.split(':')[-1]=='ParentCompanyMember')
            for axis,member in members)
        if segmented and not capital_only:
            continue
        period=context.find("x:period",ns)
        if period is None:
            continue
        start=period.findtext("x:startDate",namespaces=ns)
        end=period.findtext("x:endDate",namespaces=ns) or period.findtext("x:instant",namespaces=ns)
        if end:
            contexts[context.attrib["id"]]={"start":start,"end":end,"_capital_only":capital_only,
                "_capital_basis":"standardized_consolidated" if any('Standardized' in member for _,member in members) else 'reported_parent_consolidated'}
    for unit in root.findall("x:unit",ns):
        measures=[(x.text or "").split(":")[-1] for x in unit.findall("x:measure",ns)]
        if len(measures)==1 and measures[0] in ("USD","shares","pure"):
            units[unit.attrib["id"]]=measures[0]
        elif (unit.findtext("x:divide/x:unitNumerator/x:measure",namespaces=ns) or "").split(":")[-1]=="USD" and (unit.findtext("x:divide/x:unitDenominator/x:measure",namespaces=ns) or "").split(":")[-1]=="shares":
            units[unit.attrib["id"]]="USD/shares"
    facts={}
    for el in root:
        context=contexts.get(el.attrib.get("contextRef")); unit=units.get(el.attrib.get("unitRef"))
        if not context or not unit or not el.tag.startswith("{"):
            continue
        uri,tag=el.tag[1:].split("}",1)
        namespace="us-gaap" if "/us-gaap/" in uri else "dei" if "/dei/" in uri else None
        capital_tag=any(tag in aliases for aliases in CAPITAL_TAGS.values())
        if capital_tag and unit=="pure":
            namespace="bank-capital" if namespace is None else namespace
        if context.get("_capital_only") and not capital_tag:
            continue
        if namespace is None:
            continue
        try:
            value=float(el.text)
        except (TypeError,ValueError):
            continue
        if not math.isfinite(value):
            continue
        row={k:v for k,v in context.items() if not k.startswith("_")}
        row.update(val=value,filed=report["filed_date"],form=report["form"],accn=report["accession_number"])
        if context.get("_capital_only"):
            row["capital_basis"]=context['_capital_basis']
        facts.setdefault(namespace,{}).setdefault(tag,{"units":{}})["units"].setdefault(unit,[]).append(row)
    if not facts:
        raise RuntimeError("Filing instance contains no supported consolidated standard facts")
    return {"facts":facts}


def merge_company_facts(original,additional):
    # Copy tag/units containers; preserve all prior filings and availability.
    merged={"facts":{}}
    for data in (original,additional):
        for namespace,tags in (data.get("facts") or {}).items():
            for tag,node in tags.items():
                target=merged["facts"].setdefault(namespace,{}).setdefault(tag,{"units":{}})["units"]
                for unit,rows in (node.get("units") or {}).items():
                    target.setdefault(unit,[]).extend(rows)
    return merged


def _fact_priority(filed,alias_index,tag,key):
    # For banks, contract revenue can cover fees alone. Prefer explicitly
    # reported total revenue net of interest when available for that period.
    bank_total=key=="revenue" and tag=="RevenuesNetOfInterestExpense"
    return (bank_total,filed or "",-alias_index)


def reported_debt(rec):
    # DebtCurrent already includes current maturities and short-term debt.
    # Never add a current-maturity subtotal to it a second time.
    current=rec.get("debt_all_current")
    noncurrent=rec.get("debt_noncurrent")
    if current is not None and noncurrent is not None:
        return float(current)+float(noncurrent)
    if rec.get("debt_total") is not None and rec.get("debt_short_term") is not None:
        return float(rec["debt_total"])+float(rec["debt_short_term"])
    if rec.get("debt_current") is not None and noncurrent is not None and rec.get("debt_short_term") is not None:
        return float(rec["debt_current"])+float(noncurrent)+float(rec["debt_short_term"])
    if rec.get("debt_total") is not None:
        return rec["debt_total"]
    if rec.get("debt_current") is not None and noncurrent is not None:
        return float(rec["debt_current"])+float(noncurrent)
    return None


def debt_basis(rec):
    if rec.get("debt_all_current") is not None and rec.get("debt_noncurrent") is not None:
        return "reported_current_plus_noncurrent"
    if rec.get("debt_short_term") is not None and rec.get("debt_total") is not None:
        return "reported_long_term_total_plus_short_term_borrowings"
    if rec.get("debt_short_term") is not None and rec.get("debt_current") is not None and rec.get("debt_noncurrent") is not None:
        return "reported_current_maturities_plus_noncurrent_plus_short_term"
    return "long_term_debt_proxy" if reported_debt(rec) is not None else "unknown"

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
        "eps_diluted": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
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
            "LongTermDebtAndCapitalLeaseObligationsCurrent",
            "LongTermDebtCurrent",
        ],
        "debt_all_current": ["DebtCurrent"],
        "debt_short_term": ["ShortTermBorrowings", "ShortTermDebt"],
        "debt_noncurrent": [
            "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
            "LongTermDebtAndCapitalLeaseObligations",
            "LongTermDebtNoncurrent",
        ],
        "debt_total": ["LongTermDebtCurrentAndNoncurrent", "LongTermDebtAndFinanceLeaseObligations", "LongTermDebt"],
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
        rec["total_debt"] = reported_debt(rec)
        rec["reported_debt_basis"] = debt_basis(rec)
        ocf, capex = rec.get("operating_cash_flow"), rec.get("capex")
        rec["free_cash_flow"] = None if ocf is None or capex is None else float(ocf) - abs(float(capex))
        for k in list(rec):
            if k.startswith(("_filed_", "debt_")):
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
        "eps_diluted": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
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
            "LongTermDebtAndCapitalLeaseObligationsCurrent",
            "LongTermDebtCurrent",
        ],
        "debt_all_current": ["DebtCurrent"],
        "debt_short_term": ["ShortTermBorrowings", "ShortTermDebt"],
        "debt_noncurrent": [
            "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
            "LongTermDebtAndCapitalLeaseObligations",
            "LongTermDebtNoncurrent",
        ],
        "debt_total": ["LongTermDebtCurrentAndNoncurrent", "LongTermDebtAndFinanceLeaseObligations", "LongTermDebt"],
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
        rec["total_debt"] = reported_debt(rec)
        rec["reported_debt_basis"] = debt_basis(rec)
        ocf, capex = rec.get("operating_cash_flow"), rec.get("capex")
        rec["free_cash_flow"] = None if ocf is None or capex is None else float(ocf) - abs(float(capex))
        for k in list(rec):
            if k.startswith(("_filed_", "debt_")):
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
