import argparse,asyncio,sys,time
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1];sys.path.insert(0,str(API_DIR));load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.providers.sec import SECProvider,facts_by_period

async def main():
 p=argparse.ArgumentParser(description="Ingest annual fundamentals from official SEC Company Facts")
 p.add_argument("--tickers",nargs="*");p.add_argument("--all",action="store_true");p.add_argument("--batch-size",type=int,default=10);p.add_argument("--offset",type=int,default=0);p.add_argument("--delay",type=float,default=.15);p.add_argument("--years",type=int,default=10);a=p.parse_args()
 db=get_supabase();provider=SECProvider()
 companies=db.table("companies").select("id,ticker,cik").eq("is_sp500",True).order("ticker").execute().data or []
 if a.tickers:
  wanted={x.upper() for x in a.tickers};companies=[x for x in companies if x["ticker"] in wanted]
 elif not a.all: companies=companies[a.offset:a.offset+a.batch_size]
 ok=failed=saved=0
 for i,c in enumerate(companies):
  if i and a.delay: time.sleep(a.delay)
  if not c.get("cik"):\n   c["cik"]=ticker_map.get(c["ticker"])\n   if c.get("cik"): db.table("companies").update({"cik":c["cik"]}).eq("id",c["id"]).execute()\n  if not c.get("cik"): print(c["ticker"],"missing SEC CIK mapping");failed+=1;continue
  try:
   result=await provider.company_facts(c["cik"]);rows=facts_by_period(result.value,a.years);n=0
   for x in rows:
    payload={"company_id":c["id"],"period_end":x["period_end"],"period_type":"annual","revenue":x.get("revenue"),"operating_income":x.get("operating_income"),"net_income":x.get("net_income"),"eps_diluted":x.get("eps_diluted"),"free_cash_flow":x.get("free_cash_flow"),"capex":x.get("capex"),"cash":x.get("cash"),"total_debt":x.get("total_debt"),"source":"sec"}
    db.table("financial_metrics").upsert(payload,on_conflict="company_id,period_end,period_type").execute();n+=1
   ok+=1;saved+=n;print(c["ticker"],"SEC rows=",n)
  except Exception as e: failed+=1;print(c["ticker"],"SEC unavailable:",e)
 print(f"Done companies_ok={ok} failed={failed} rows_saved={saved}")
if __name__=="__main__": asyncio.run(main())
