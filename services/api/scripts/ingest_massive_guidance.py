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
    ap=argparse.ArgumentParser(); ap.add_argument("--ticker"); ap.add_argument("--all",action="store_true"); ap.add_argument("--batch-size",type=int,default=25); ap.add_argument("--offset",type=int,default=0); ap.add_argument("--delay",type=float,default=.25)
    a=ap.parse_args(); db=get_supabase(); provider=MassiveProvider()
    q=db.table("companies").select("id,ticker").eq("is_sp500",True).order("ticker")
    companies=q.execute().data or []
    if a.ticker: companies=[x for x in companies if x["ticker"]==a.ticker.upper()]
    elif not a.all: companies=companies[a.offset:a.offset+a.batch_size]
    for c in companies:
        try:
            rows=await provider.guidance(c["ticker"]); payload=[]
            for x in rows:
                payload.append({"company_id":c["id"],"event_date":x.get("date"),"event_time":x.get("time"),"fiscal_year":x.get("fiscal_year"),"fiscal_period":x.get("fiscal_period"),"release_type":x.get("release_type"),"eps_method":x.get("eps_method"),"revenue_method":x.get("revenue_method"),"eps_guidance_low":num(x.get("min_eps_guidance")),"eps_guidance_high":num(x.get("max_eps_guidance")),"revenue_guidance_low":num(x.get("min_revenue_guidance")),"revenue_guidance_high":num(x.get("max_revenue_guidance")),"consensus_eps_at_event":num(x.get("estimated_eps_guidance")),"consensus_revenue_at_event":num(x.get("estimated_revenue_guidance")),"previous_eps_guidance_low":num(x.get("previous_min_eps_guidance")),"previous_eps_guidance_high":num(x.get("previous_max_eps_guidance")),"previous_revenue_guidance_low":num(x.get("previous_min_revenue_guidance")),"previous_revenue_guidance_high":num(x.get("previous_max_revenue_guidance")),"notes":x.get("notes"),"source":"massive_benzinga","source_record_id":x.get("benzinga_id")})
            if payload: db.table("corporate_guidance_events").upsert(payload,on_conflict="company_id,event_date,fiscal_year,fiscal_period,source,source_record_id").execute()
            print(c["ticker"],"guidance",len(payload))
        except Exception as e: print(c["ticker"],"ERROR",str(e))
        await asyncio.sleep(a.delay)
if __name__=="__main__": asyncio.run(main())
