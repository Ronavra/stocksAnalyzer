import sys, asyncio, argparse, time
from datetime import date, timedelta
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.providers.twelvedata import TwelveDataProvider
from app.market_calendar import latest_completed_session

db=get_supabase(); provider=TwelveDataProvider(); end=latest_completed_session()

def parse_args():
 p=argparse.ArgumentParser(description="Incrementally ingest S&P 500 price history in resumable batches")
 p.add_argument("--batch-size",type=int,default=25)
 p.add_argument("--offset",type=int,default=0)
 p.add_argument("--bootstrap-years",type=int,default=6)
 p.add_argument("--tickers",nargs="*")
 p.add_argument("--delay",type=float,default=8.5,help="Seconds between provider requests")
 p.add_argument("--all",action="store_true",help="Process the full S&P 500 universe plus benchmark")
 return p.parse_args()

args=parse_args()
q=db.table("companies").select("id,ticker,is_sp500,scoring_profile").or_("is_sp500.eq.true,scoring_profile.eq.benchmark").order("ticker")
companies=q.execute().data or []
if args.tickers:
 wanted={x.upper() for x in args.tickers}; companies=[c for c in companies if c["ticker"].upper() in wanted]
elif not args.all:
 companies=companies[args.offset:args.offset+args.batch_size]

print(f"Processing {len(companies)} companies" + (" (all mode)" if args.all else f" (offset={args.offset}, batch_size={args.batch_size})"))
for idx,c in enumerate(companies):
 try:
  latest=(db.table("price_history").select("price_date").eq("company_id",c["id"]).eq("source","twelvedata").order("price_date",desc=True).limit(1).execute().data or [])
  start=(date.fromisoformat(latest[0]["price_date"])+timedelta(days=1)) if latest else end-timedelta(days=365*args.bootstrap_years)
  # Incremental refresh: fetch from the day after the latest stored bar.
  # A Friday bar must not be treated as current on Monday.
  if latest:
   latest_date=date.fromisoformat(latest[0]["price_date"])
   if latest_date>=end:
    print(c["ticker"],"price history already current through",latest_date); continue
  if start>end:
   print(c["ticker"],"price history already current"); continue
  if idx>0 and args.delay>0: time.sleep(args.delay)
  result=asyncio.run(provider.historical_prices(c["ticker"],str(start),str(end)))
  payload=[]
  for r in result.value:
   d=r.get("date"); close=r.get("close")
   if not d or close is None: continue
   payload.append({"company_id":c["id"],"price_date":d,"open":r.get("open"),"high":r.get("high"),"low":r.get("low"),"close":close,"volume":r.get("volume"),"source":"twelvedata"})
  for i in range(0,len(payload),250):
   db.table("price_history").upsert(payload[i:i+250],on_conflict="company_id,price_date,source").execute()
  print(c["ticker"],"price rows saved=",len(payload))
 except Exception as e:
  print(c["ticker"],"price history unavailable:",e)
  if "HTTP 429" in str(e):
   print("Rate limit reached. Stop this batch and rerun the SAME offset later; existing rows will be skipped incrementally.")
   break

if args.all:
 print("Full-universe pass complete. Re-run --all later to fill any remaining gaps.")
elif not args.tickers:
 next_offset=args.offset+len(companies)
 print(f"Batch complete. Next command: python scripts\\ingest_prices.py --offset {next_offset} --batch-size {args.batch_size}")
