import argparse, asyncio, sys
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.providers.massive import MassiveProvider

def num(v):
    try: return float(v) if v not in (None,"","None") else None
    except (TypeError,ValueError): return None

async def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--ticker"); ap.add_argument("--all",action="store_true")
    ap.add_argument("--batch-size",type=int,default=25); ap.add_argument("--offset",type=int,default=0)
    ap.add_argument("--delay",type=float,default=.25); a=ap.parse_args()
    db=get_supabase(); provider=MassiveProvider()
    companies=db.table("companies").select("id,ticker").eq("is_sp500",True).order("ticker").execute().data or []
    if a.ticker: companies=[x for x in companies if x["ticker"]==a.ticker.upper()]
    elif not a.all: companies=companies[a.offset:a.offset+a.batch_size]
    for c in companies:
        try:
            rows=await provider.earnings(c["ticker"]); payload=[]
            for x in rows:
                reported=x.get("date")
                if not reported: continue
                actual_eps=num(x.get("actual_eps")); estimated_eps=num(x.get("estimated_eps"))
                actual_rev=num(x.get("actual_revenue")); estimated_rev=num(x.get("estimated_revenue"))
                eps_surprise=(actual_eps-estimated_eps) if actual_eps is not None and estimated_eps is not None else None
                eps_pct=(eps_surprise/abs(estimated_eps)*100) if eps_surprise is not None and estimated_eps not in (None,0) else None
                rev_surprise=(actual_rev-estimated_rev) if actual_rev is not None and estimated_rev is not None else None
                rev_pct=(rev_surprise/abs(estimated_rev)*100) if rev_surprise is not None and estimated_rev not in (None,0) else None
                payload.append({"company_id":c["id"],"reported_date":reported,"fiscal_date_ending":None,
                  "reported_eps":actual_eps,"estimated_eps":estimated_eps,"surprise":eps_surprise,"surprise_percent":eps_pct,
                  "actual_revenue":actual_rev,"estimated_revenue":estimated_rev,"revenue_surprise":rev_surprise,
                  "revenue_surprise_percent":rev_pct,"event_time":x.get("time"),"source":"massive_benzinga",
                  "source_record_id":x.get("benzinga_id")})
            if payload: db.table("earnings_events").upsert(payload,on_conflict="company_id,reported_date,source").execute()
            print(c["ticker"],"earnings",len(payload))
        except Exception as e: print(c["ticker"],"ERROR",str(e))
        await asyncio.sleep(a.delay)
if __name__=="__main__": asyncio.run(main())
