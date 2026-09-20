import sys, asyncio, argparse, time
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.providers.alphavantage import AlphaVantageProvider
db=get_supabase(); provider=AlphaVantageProvider()
p=argparse.ArgumentParser(); p.add_argument("--batch-size",type=int,default=10); p.add_argument("--offset",type=int,default=0); p.add_argument("--delay",type=float,default=13); a=p.parse_args()
companies=(db.table("companies").select("id,ticker").eq("is_sp500",True).order("ticker").range(a.offset,a.offset+a.batch_size-1).execute().data or [])
for i,c in enumerate(companies):
 try:
  if i: time.sleep(a.delay)
  d=asyncio.run(provider.earnings(c["ticker"])).value
  q=d.get("quarterlyEarnings",[])
  usable=[x for x in q if x.get("reportedDate") and x.get("reportedEPS") not in (None,"None") and x.get("estimatedEPS") not in (None,"None")]
  print(c["ticker"],"quarterly=",len(q),"usable_surprises=",len(usable),"oldest=",usable[-1].get("reportedDate") if usable else None,"latest=",usable[0].get("reportedDate") if usable else None)
 except Exception as e: print(c["ticker"],"earnings unavailable:",e)
