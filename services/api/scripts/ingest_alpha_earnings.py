import sys, asyncio, argparse, time
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.providers.alphavantage import AlphaVantageProvider
db=get_supabase(); provider=AlphaVantageProvider()
p=argparse.ArgumentParser(); p.add_argument("--all",action="store_true"); p.add_argument("--batch-size",type=int,default=10); p.add_argument("--offset",type=int,default=0); p.add_argument("--delay",type=float,default=13); a=p.parse_args()
companies=(db.table("companies").select("id,ticker").eq("is_sp500",True).order("ticker").execute().data or [])
if not a.all: companies=companies[a.offset:a.offset+a.batch_size]
print("Ingesting earnings for",len(companies),"companies")
for i,c in enumerate(companies):
 try:
  if i: time.sleep(a.delay)
  q=asyncio.run(provider.earnings(c["ticker"])).value.get("quarterlyEarnings",[])
  payload=[]
  for x in q:
   rd=x.get("reportedDate"); rep=x.get("reportedEPS"); est=x.get("estimatedEPS")
   if not rd or rep in (None,"None") or est in (None,"None"): continue
   payload.append({"company_id":c["id"],"reported_date":rd,"fiscal_date_ending":x.get("fiscalDateEnding"),
    "reported_eps":rep,"estimated_eps":est,"surprise":x.get("surprise"),
    "surprise_percent":x.get("surprisePercentage"),"source":"alphavantage"})
  if payload: db.table("earnings_events").upsert(payload,on_conflict="company_id,reported_date,source").execute()
  print(c["ticker"],"earnings saved=",len(payload))
 except Exception as e:
  print(c["ticker"],"earnings unavailable:",e)
  if "frequency" in str(e).lower() or "rate" in str(e).lower(): break
