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
    rows=(db.table("earnings_events").select("captured_at")
          .eq("source","massive_benzinga")
          .order("captured_at",desc=True).limit(1).execute().data or [])
    if not rows or not rows[0].get("captured_at"):
        return (datetime.now(timezone.utc)-timedelta(days=7)).isoformat()
    dt=datetime.fromisoformat(rows[0]["captured_at"].replace("Z","+00:00"))
    return (dt-timedelta(hours=lookback_hours)).astimezone(timezone.utc).isoformat()

def payload_for(company_id,x,captured_at):
    reported=x.get("date")
    if not reported:
        return None
    actual_eps=num(x.get("actual_eps"))
    estimated_eps=num(x.get("estimated_eps"))
    actual_rev=num(x.get("actual_revenue"))
    estimated_rev=num(x.get("estimated_revenue"))
    eps_surprise=(actual_eps-estimated_eps) if actual_eps is not None and estimated_eps is not None else None
    eps_pct=(eps_surprise/abs(estimated_eps)*100) if eps_surprise is not None and estimated_eps not in (None,0) else None
    rev_surprise=(actual_rev-estimated_rev) if actual_rev is not None and estimated_rev is not None else None
    rev_pct=(rev_surprise/abs(estimated_rev)*100) if rev_surprise is not None and estimated_rev not in (None,0) else None
    return {
        "company_id":company_id,
        "reported_date":reported,
        "fiscal_date_ending":None,
        "reported_eps":actual_eps,
        "estimated_eps":estimated_eps,
        "surprise":eps_surprise,
        "surprise_percent":eps_pct,
        "actual_revenue":actual_rev,
        "estimated_revenue":estimated_rev,
        "revenue_surprise":rev_surprise,
        "revenue_surprise_percent":rev_pct,
        "event_time":x.get("time"),
        "source":"massive_benzinga",
        "source_record_id":x.get("benzinga_id"),
        "captured_at":captured_at,
    }

async def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--ticker")
    ap.add_argument("--all",action="store_true")
    ap.add_argument("--incremental",action="store_true",help="Fetch all provider records updated since the last local sync using one bulk request")
    ap.add_argument("--since",help="Override Massive last_updated lower bound (ISO 8601)")
    ap.add_argument("--lookback-hours",type=int,default=30,help="Overlap window to avoid missing provider updates")
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
        rows=await provider.earnings(updated_since=since)
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
            db.table("earnings_events").upsert(payload[i:i+250],on_conflict="company_id,reported_date,source").execute()
        print(f"Massive incremental earnings since={since} provider_rows={len(rows)} saved={len(payload)} ignored_non_sp500={ignored} api_calls=1")
        return

    if a.ticker:
        companies=[x for x in companies if normalize_ticker(x["ticker"])==normalize_ticker(a.ticker)]
    elif not a.all:
        companies=companies[a.offset:a.offset+a.batch_size]

    for i,c in enumerate(companies):
        try:
            if i and a.delay:
                await asyncio.sleep(a.delay)
            rows=await provider.earnings(c["ticker"])
            payload=[payload_for(c["id"],x,captured_at) for x in rows]
            payload=[x for x in payload if x]
            if payload:
                db.table("earnings_events").upsert(payload,on_conflict="company_id,reported_date,source").execute()
            print(c["ticker"],"earnings",len(payload))
        except Exception as e:
            print(c["ticker"],"ERROR",str(e))

if __name__=="__main__":
    asyncio.run(main())
