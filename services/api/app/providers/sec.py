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

def facts_by_period(data:dict,years:int=10):
    facts=(data.get("facts") or {}).get("us-gaap") or {}
    aliases={
      "revenue":["RevenueFromContractWithCustomerExcludingAssessedTax","Revenues","SalesRevenueNet"],
      "operating_income":["OperatingIncomeLoss"],
      "net_income":["NetIncomeLoss","ProfitLoss"],
      "eps_diluted":["EarningsPerShareDiluted"],
      "operating_cash_flow":["NetCashProvidedByUsedInOperatingActivities"],
      "capex":["PaymentsToAcquirePropertyPlantAndEquipment"],
      "cash":["CashAndCashEquivalentsAtCarryingValue","CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
      "total_debt":["LongTermDebtAndFinanceLeaseObligationsCurrent","LongTermDebtCurrent","LongTermDebtNoncurrent","LongTermDebt"],
      "equity":["StockholdersEquity"],
      "shares":["CommonStocksIncludingAdditionalPaidInCapitalMember"], # intentionally not used until normalized
    }
    units={"eps_diluted":["USD/shares"],"revenue":["USD"],"operating_income":["USD"],"net_income":["USD"],"operating_cash_flow":["USD"],"capex":["USD"],"cash":["USD"],"total_debt":["USD"],"equity":["USD"]}
    out={}
    for key,tags in aliases.items():
      if key=="shares": continue
      for tag in tags:
        node=facts.get(tag)
        if not node: continue
        rows=[]
        for unit in units.get(key,["USD"]):
          rows.extend((node.get("units") or {}).get(unit) or [])
        # 10-K facts only; use filing date as point-in-time provenance and dedupe restatements by latest filed.
        rows=[x for x in rows if x.get("form") in ("10-K","10-K/A") and x.get("end") and x.get("val") is not None]
        if rows:
          for x in rows:
            d=x["end"]; rec=out.setdefault(d,{"period_end":d,"filed_date":x.get("filed"),"accn":x.get("accn")})
            old=rec.get("_filed_"+key,"")
            if (x.get("filed") or "")>=old:
              rec[key]=x["val"]; rec["_filed_"+key]=x.get("filed") or ""
          break
    for rec in out.values():
      ocf=rec.get("operating_cash_flow"); capex=rec.get("capex")
      rec["free_cash_flow"]=None if ocf is None or capex is None else float(ocf)-abs(float(capex))
      for k in list(rec):
        if k.startswith("_filed_"): rec.pop(k)
    return sorted(out.values(),key=lambda x:x["period_end"],reverse=True)[:years]
