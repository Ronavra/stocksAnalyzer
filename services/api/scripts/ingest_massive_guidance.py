import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")

from app.db.client import get_supabase
from app.providers.massive import MassiveProvider

def num(v):
    try:
        return float(v) if v not in (None,"","None") else None
    except (TypeError,ValueError):
        return None

def normalize_ticker(v):
    return str(v or "").upper().replace(".","-")

def watermark(db,lookback_hours):
    rows=(db.table("corporate_guidance_events").select("captured_at")
          .eq("source","massive_benzinga")
          .order("captured_at",desc=True).limit(1).execute().data or [])
    if not rows or not rows[0].get("captured_at"):
        return (datetime.now(timezone.utc)-timedelta(days=7)).isoformat()
    dt=datetime.fromisoformat(rows[0]["captured_at"].replace("Z","+00:00"))
    return (dt-timedelta(hours=lookback_hours)).astimezone(timezone.utc).isoformat()

def payload_for(company_id,x,captured_at):
    event_date=x.get("date")
    if not event_date:
        return None
    return {
        "company_id":company_id,
        "event_date":event_date,
        "event_time":x.get("time"),
        "fiscal_year":x.get("fiscal_year"),
        "fiscal_period":x.get("fiscal_period"),
        "release_type":x.get("release_type"),
        "eps_method":x.get("eps_method"),
        "revenue_method":x.get("revenue_method"),
        "eps_guidance_low":num(x.get("min_eps_guidance")),
        "eps_guidance_high":num(x.get("max_eps_guidance")),
        "revenue_guidance_low":num(x.get("min_revenue_guidance")),
        "revenue_guidance_high":num(x.get("max_revenue_guidance")),
        "consensus_eps_at_event":num(x.get("estimated_eps_guidance")),
        "consensus_revenue_at_event":num(x.get("estimated_revenue_guidance")),
        "previous_eps_guidance_low":num(x.get("previous_min_eps_guidance")),
        "previous_eps_guidance_high":num(x.get("previous_max_eps_guidance")),
        "previous_revenue_guidance_low":num(x.get("previous_min_revenue_guidance")),
        "previous_revenue_guidance_high":num(x.get("previous_max_revenue_guidance")),
        "notes":x.get("notes"),
        "source":"massive_benzinga",
        "source_record_id":x.get("benzinga_id"),
        "captured_at":captured_at,
    }

async def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--ticker")
    ap.add_argument("--all",action="store_true")
    ap.add_argument("--incremental",action="store_true")
    ap.add_argument("--since")
    ap.add_argument("--lookback-hours",type=int,default=30)
    ap.add_argument("--batch-size",type=int,default=25)
    ap.add_argument("--offset",type=int,default=0)
    ap.add_argument("--delay",type=float,default=.25)
    a=ap.parse_args()

    db=get_supabase()
    provider=MassiveProvider()
    companies=db.table("companies").select("id,ticker").eq("is_sp500",True).order("ticker").execute().data or []
    by_ticker={normalize_ticker(x["ticker"]):x["id"] for x in companies}
    captured_at=datetime.now(timezone.utc).isoformat()

    if a.incremental:
        since=a.since or watermark(db,a.lookback_hours)
        rows=await provider.guidance(updated_since=since)
        payload=[]
        ignored=0
        for x in rows:
            cid=by_ticker.get(normalize_ticker(x.get("ticker")))
            if not cid:
                ignored+=1
                continue
            item=payload_for(cid,x,captured_at)
            if item:
                payload.append(item)
        for i in range(0,len(payload),250):
            db.table("corporate_guidance_events").upsert(
                payload[i:i+250],
                on_conflict="company_id,event_date,fiscal_year,fiscal_period,source,source_record_id"
            ).execute()
        print(f"Massive incremental guidance since={since} provider_rows={len(rows)} saved={len(payload)} ignored_non_sp500={ignored} api_calls=1")
        return

    if a.ticker:
        companies=[x for x in companies if normalize_ticker(x["ticker"])==normalize_ticker(a.ticker)]
    elif not a.all:
        companies=companies[a.offset:a.offset+a.batch_size]

    for i,c in enumerate(companies):
        try:
            if i and a.delay:
                await asyncio.sleep(a.delay)
            rows=await provider.guidance(c["ticker"])
            payload=[payload_for(c["id"],x,captured_at) for x in rows]
            payload=[x for x in payload if x]
            if payload:
                db.table("corporate_guidance_events").upsert(
                    payload,
                    on_conflict="company_id,event_date,fiscal_year,fiscal_period,source,source_record_id"
                ).execute()
            print(c["ticker"],"guidance",len(payload))
        except Exception as e:
            print(c["ticker"],"ERROR",str(e))

if __name__=="__main__":
    asyncio.run(main())
