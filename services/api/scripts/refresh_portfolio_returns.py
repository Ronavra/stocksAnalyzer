"""Refresh dividend-adjusted evaluation series only for frozen picks and SPY."""
import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.providers.twelvedata import TwelveDataProvider
from app.research.prospective_metrics import paged
from app.research.weekly_rank_metrics import number
from app.market_calendar import latest_completed_session


def normalized_series(rows, required_dates, end):
    by_date={}
    for row in rows:
        day=row.get("price_date")
        value=number(row.get("close"))
        if not day or day>end:
            continue
        if value is None or value<=0:
            raise RuntimeError("Adjusted series contains an invalid close")
        if day in by_date and by_date[day]!=value:
            raise RuntimeError("Adjusted series contains conflicting session closes")
        by_date[day]=value
    missing=set(required_dates)-set(by_date)
    if missing:
        raise RuntimeError(f"Adjusted series missing {len(missing)} stored market sessions; snapshot preserved")
    if not by_date:
        raise RuntimeError("No adjusted prices returned; snapshot preserved")
    return [{"price_date":day,"close":by_date[day]} for day in sorted(by_date)]


def refresh(db,provider,max_age_hours=20,delay=8.5):
    cohorts=paged(db.table("recommendation_cohorts").select("signal_date,status").order("signal_date"))
    published=[c for c in cohorts if c["status"]=="published"]
    if not published:
        return {"status":"not_due","reason":"no_published_cohorts"}
    start=min(c["signal_date"] for c in published)
    end=latest_completed_session().isoformat()
    predictions=paged(db.table("research_predictions").select("company_id").order("id"))
    ids={p["company_id"] for p in predictions}
    companies=db.table("companies").select("id,ticker").order("id").execute().data or []
    spy=next((c for c in companies if c["ticker"]=="SPY"),None)
    if not spy:
        raise RuntimeError("SPY is unavailable")
    ids.add(spy["id"])
    companies=sorted((c for c in companies if c["id"] in ids),key=lambda c:(c["ticker"]!="SPY",c["ticker"]))
    existing={r["company_id"]:r for r in db.table("portfolio_return_series").select("company_id,first_date,last_date,observed_at")
              .in_("company_id",sorted(ids)).execute().data or []}
    now=datetime.now(timezone.utc)
    refreshed=[]; reused=[]; errors=[]
    attempts=0
    for company in companies:
        previous=existing.get(company["id"])
        if previous and previous["first_date"]<=start and previous["last_date"]>=end:
            observed=datetime.fromisoformat(previous["observed_at"].replace("Z","+00:00"))
            if 0<=(now-observed).total_seconds()<max_age_hours*3600:
                reused.append(company["ticker"])
                continue
        if attempts and delay:
            time.sleep(delay)
        attempts+=1
        try:
            prices=paged(db.table("price_history").select("price_date").eq("company_id",company["id"])
                         .gte("price_date",start).lte("price_date",end).order("price_date"))
            required={r["price_date"] for r in prices}
            # Re-fetch the complete span: later dividends rescale older closes.
            result=asyncio.run(provider.historical_total_returns(company["ticker"],start,
                             (datetime.fromisoformat(end)+timedelta(days=1)).date().isoformat()))
            bars=normalized_series(result.value,required,end)
            payload={"company_id":company["id"],"source":"twelvedata_adjust_all","adjustment":"all",
                     "observed_at":datetime.now(timezone.utc).isoformat(),"first_date":bars[0]["price_date"],
                     "last_date":bars[-1]["price_date"],"bars":bars}
            db.table("portfolio_return_series").upsert(payload,on_conflict="company_id").execute()
            refreshed.append(company["ticker"])
            print(company["ticker"],"adjusted evaluation sessions",len(bars),flush=True)
        except Exception as exc:
            errors.append({"ticker":company["ticker"],"error":str(exc)[:400]})
    return {"status":"partial" if errors else "success","start_date":start,"end_date":end,
            "source":"twelvedata_adjust_all","refreshed":refreshed,"reused":reused,"errors":errors,
            "request_attempts":provider.request_attempts_total}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--max-age-hours",type=float,default=20)
    parser.add_argument("--delay",type=float,default=8.5)
    args=parser.parse_args()
    db=get_supabase(); provider=TwelveDataProvider(); provider.request_budget=60
    run=db.table("pipeline_runs").insert({"pipeline":"portfolio_returns_refresh","status":"running",
              "started_at":datetime.now(timezone.utc).isoformat()}).execute().data or []
    run_id=run[0]["id"] if run else None
    try:
        report=refresh(db,provider,args.max_age_hours,args.delay)
        if run_id:
            db.table("pipeline_runs").update({"status":"error" if report["status"]=="partial" else "success",
                 "finished_at":datetime.now(timezone.utc).isoformat(),"metadata":report,
                 "error_message":"Adjusted evaluation series incomplete" if report.get("errors") else None}).eq("id",run_id).execute()
        print(json.dumps(report),flush=True)
        if report["status"]=="partial":
            raise RuntimeError("Total-return coverage incomplete; price-return comparison remains separate")
    except Exception as exc:
        if run_id:
            db.table("pipeline_runs").update({"status":"error","finished_at":datetime.now(timezone.utc).isoformat(),
                  "error_message":str(exc)[:500]}).eq("id",run_id).execute()
        raise


if __name__=="__main__":
    main()
