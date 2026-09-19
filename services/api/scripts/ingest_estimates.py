import argparse,asyncio,sys
from datetime import date
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.providers.fmp import FMPProvider

async def ingest(ticker):
    db=get_supabase(); provider=FMPProvider()
    company=(db.table("companies").select("id").eq("ticker",ticker.upper()).limit(1).execute().data or [])
    if not company: raise RuntimeError(f"{ticker} is not in companies")
    result=await provider.analyst_estimates(ticker.upper(),"annual")
    rows=result.value or []; saved=0
    for row in rows:
        period=row.get("date")
        if not period: continue
        payload={"company_id":company[0]["id"],"estimate_date":str(date.today()),"period_end":period,
          "period_type":"annual","estimated_revenue":row.get("revenueAvg"),
          "estimated_eps":row.get("epsAvg"),"analyst_count_revenue":row.get("numAnalystsRevenue"),
          "analyst_count_eps":row.get("numAnalystsEps"),"source":"fmp"}
        db.table("analyst_estimates").upsert(payload,on_conflict="company_id,estimate_date,period_end,period_type,source").execute(); saved+=1
    print(f"{ticker.upper()} estimates saved={saved}")

async def main():
    p=argparse.ArgumentParser(); p.add_argument("tickers",nargs="+"); a=p.parse_args()
    for ticker in a.tickers:
        try: await ingest(ticker)
        except Exception as exc: print(f"FAILED {ticker}: {exc}")
if __name__=="__main__": asyncio.run(main())
