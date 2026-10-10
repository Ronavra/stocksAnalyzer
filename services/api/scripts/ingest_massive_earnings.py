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
    return str(v or "").upper().replace(".","-").replace("/","-")

def missing_earnings_companies(db):
    # Empty resource embedding performs an anti-join without downloading the
    # full earnings history simply to find new/uncovered constituents.
    return (db.table("companies").select("id,ticker,earnings_events()")
            .eq("is_sp500",True).is_("earnings_events","null")
            .order("ticker").execute().data or [])

def watermark(db,lookback_hours):
    # A failed bulk write may have saved earlier batches. Only a completed
    # refresh can advance the cursor, or a retry could skip unsaved records.
    rows=(db.table("pipeline_runs").select("started_at")
          .eq("pipeline","earnings_refresh").eq("status","success")
          .order("started_at",desc=True).limit(1).execute().data or [])
    if not rows or not rows[0].get("started_at"):
        return (datetime.now(timezone.utc)-timedelta(days=7)).isoformat()
    dt=datetime.fromisoformat(rows[0]["started_at"].replace("Z","+00:00"))
    return (dt-timedelta(hours=lookback_hours)).astimezone(timezone.utc).isoformat()

def revision_order(row):
    try:
        updated=datetime.fromisoformat(str(row.get("last_updated") or "").replace("Z","+00:00"))
        if updated.tzinfo is None:
            updated=updated.replace(tzinfo=timezone.utc)
    except ValueError:
        updated=datetime.min.replace(tzinfo=timezone.utc)
    # At an equal revision timestamp, prefer the complete observation and use
    # the provider ID as a stable tie break. Never combine different EPS bases.
    complete=sum(num(row.get(k)) is not None for k in
                 ("actual_eps","actual_revenue","estimated_eps","estimated_revenue"))
    return updated,complete,str(row.get("benzinga_id") or "")

def unique_payload(rows,by_ticker,captured_at):
    selected={}
    ignored=0
    duplicates=0
    for row in rows:
        cid=by_ticker.get(normalize_ticker(row.get("ticker")))
        if cid is None:
            ignored+=1
            continue
        item=payload_for(cid,row,captured_at)
        if item is None:
            continue
        key=(cid,item["reported_date"],item["source"])
        order=revision_order(row)
        if key in selected:
            duplicates+=1
        if key not in selected or order>selected[key][0]:
            selected[key]=(order,item)
    return [selected[k][1] for k in sorted(selected)],ignored,duplicates

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
    ap.add_argument("--backfill-missing",action="store_true",help="Fetch full earnings history only for current companies with no earnings observations")
    ap.add_argument("--since",help="Override Massive last_updated lower bound (ISO 8601)")
    ap.add_argument("--lookback-hours",type=int,default=30,help="Overlap window to avoid missing provider updates")
    ap.add_argument("--batch-size",type=int,default=25)
    ap.add_argument("--offset",type=int,default=0)
    ap.add_argument("--delay",type=float,default=.25)
    a=ap.parse_args()
    if a.backfill_missing and (a.incremental or a.ticker or a.all):
        ap.error("--backfill-missing cannot be combined with another selection mode")

    db=get_supabase()
    provider=MassiveProvider()
    companies=db.table("companies").select("id,ticker").eq("is_sp500",True).order("ticker").execute().data or []
    by_ticker={normalize_ticker(x["ticker"]):x["id"] for x in companies}
    captured_at=datetime.now(timezone.utc).isoformat()

    if a.incremental:
        since=a.since or watermark(db,a.lookback_hours)
        rows=await provider.earnings(updated_since=since)
        payload,ignored,duplicates=unique_payload(rows,by_ticker,captured_at)
        for i in range(0,len(payload),250):
            db.table("earnings_events").upsert(payload[i:i+250],on_conflict="company_id,reported_date,source").execute()
        print(f"Massive incremental earnings since={since} provider_rows={len(rows)} saved={len(payload)} duplicates_removed={duplicates} ignored_non_sp500={ignored}")
        return

    if a.backfill_missing:
        companies=missing_earnings_companies(db)
    elif a.ticker:
        companies=[x for x in companies if normalize_ticker(x["ticker"])==normalize_ticker(a.ticker)]
    elif not a.all:
        companies=companies[a.offset:a.offset+a.batch_size]

    failures=[]
    for i,c in enumerate(companies):
        try:
            if i and a.delay:
                await asyncio.sleep(a.delay)
            # Benzinga uses dotted share classes; the database uses SEC-style
            # hyphens. Response symbols are normalized back to database IDs.
            rows=await provider.earnings(c["ticker"].replace("-","."))
            payload,_,duplicates=unique_payload(rows,by_ticker,captured_at)
            if payload:
                for start in range(0,len(payload),250):
                    db.table("earnings_events").upsert(payload[start:start+250],on_conflict="company_id,reported_date,source").execute()
            print(c["ticker"],"earnings",len(payload))
        except Exception as e:
            failures.append(c["ticker"])
            print(c["ticker"],"ERROR",str(e))
    if failures:
        raise RuntimeError("Earnings collection failed for: "+", ".join(failures))

if __name__=="__main__":
    asyncio.run(main())
