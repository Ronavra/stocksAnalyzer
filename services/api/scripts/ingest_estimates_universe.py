import sys, asyncio, argparse, time
from datetime import date
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.providers.fmp import FMPProvider

db=get_supabase(); provider=FMPProvider()

def args():
 p=argparse.ArgumentParser(description="Incrementally capture analyst-estimate snapshots for the S&P 500")
 p.add_argument("--all",action="store_true")
 p.add_argument("--batch-size",type=int,default=25)
 p.add_argument("--offset",type=int,default=0)
 p.add_argument("--delay",type=float,default=.25)
 return p.parse_args()

a=args()
companies=(db.table("companies").select("id,ticker").eq("is_sp500",True).order("ticker").execute().data or [])
if not a.all: companies=companies[a.offset:a.offset+a.batch_size]
today=str(date.today())
print(f"Capturing estimates for {len(companies)} companies")
for i,c in enumerate(companies):
 try:
  if i and a.delay: time.sleep(a.delay)
  result=asyncio.run(provider.analyst_estimates(c["ticker"],period="annual"))
  rows=result.value if isinstance(result.value,list) else []
  payload=[]
  for r in rows:
   period_end=r.get("date") or r.get("period")
   if not period_end: continue
   payload.append({"company_id":c["id"],"estimate_date":today,"period_end":period_end,
    "period_type":"annual","estimated_revenue":r.get("estimatedRevenueAvg") or r.get("revenueAvg"),
    "estimated_eps":r.get("estimatedEpsAvg") or r.get("epsAvg"),
    "analyst_count_revenue":r.get("numberAnalystsEstimatedRevenue"),
    "analyst_count_eps":r.get("numberAnalystEstimatedEps"),"source":"fmp"})
  if payload: db.table("analyst_estimates").upsert(payload,on_conflict="company_id,estimate_date,period_end,period_type,source").execute()
  print(c["ticker"],"estimate rows=",len(payload))
 except Exception as e:
  print(c["ticker"],"estimates unavailable:",e)
print("Estimate snapshot complete. Re-run on future research dates to build revision history.")
