import argparse
import json
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

HERE=Path(__file__).resolve().parent
API_DIR=HERE.parent
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")

from app.db.client import get_supabase

PY=sys.executable
FULL_PIPELINE="research_sources_refresh"
EARNINGS_PIPELINE="earnings_refresh"

def run(name,*args):
    print(f"\n=== {name} ===",flush=True)
    started=time.monotonic()
    subprocess.run([PY,str(HERE/name),*args],check=True)
    return round(time.monotonic()-started,2)

def recent_success(db,max_age_hours,pipeline):
    if not max_age_hours:
        return None
    rows=(db.table("pipeline_runs").select("*")
          .eq("pipeline",pipeline).eq("status","success")
          .order("finished_at",desc=True).limit(1).execute().data or [])
    if not rows or not rows[0].get("finished_at"):
        return None
    finished=datetime.fromisoformat(rows[0]["finished_at"].replace("Z","+00:00"))
    age=(datetime.now(timezone.utc)-finished).total_seconds()/3600
    return rows[0] if age<=max_age_hours else None

def refresh_sources(earnings_only,include_guidance,timings,sec_only=False):
    # Keep the paid earnings source fresh even if SEC access is denied.
    if not sec_only:
        timings["massive_earnings_seconds"]=run(
            "ingest_massive_earnings.py","--incremental","--lookback-hours","30"
        )
        if include_guidance:
            timings["massive_guidance_seconds"]=run(
                "ingest_massive_guidance.py","--incremental","--lookback-hours","30"
            )
    if not earnings_only:
        # SEC has a 10 req/s fair-access ceiling, not a daily quota.
        timings["sec_fundamentals_seconds"]=run(
            "ingest_sec_fundamentals.py","--all","--delay","0.16","--years","10","--quarters","16"
        )
        timings["valuation_seconds"]=run("build_daily_valuation.py")

def financial_audit(started):
    path=API_DIR/"sec_fundamentals_audit.json"
    if not path.exists():
        return None
    report=json.loads(path.read_text())
    return report if report.get("started_at","")>=started and report.get("scope")=="full_universe" else None

def main():
    ap=argparse.ArgumentParser(description="Refresh non-price research sources with API-safe incremental rules")
    ap.add_argument("--max-age-hours",type=float,default=0,help="Skip the refresh if a successful source refresh is newer than this")
    ap.add_argument("--include-guidance",action="store_true",help="Also sync Massive corporate guidance; disabled by default until plan access is verified")
    modes=ap.add_mutually_exclusive_group()
    modes.add_argument("--earnings-only",action="store_true",help="Refresh Massive earnings without SEC; use for the weekly signal freeze")
    modes.add_argument("--sec-only",action="store_true",help="Refresh SEC filings and valuation without fetching Massive earnings again")
    a=ap.parse_args()
    if a.sec_only and a.include_guidance:
        ap.error("--include-guidance cannot be combined with --sec-only")

    db=get_supabase()
    pipeline=EARNINGS_PIPELINE if a.earnings_only else FULL_PIPELINE
    mode="earnings_only" if a.earnings_only else "sec_only" if a.sec_only else "full_research_sources"
    recent=recent_success(db,a.max_age_hours,pipeline)
    if recent:
        print(f"Research sources already refreshed recently at {recent.get('finished_at')}; skipping duplicate calls.")
        return

    started=datetime.now(timezone.utc).isoformat()
    created=db.table("pipeline_runs").insert({
        "pipeline":pipeline,
        "started_at":started,
        "status":"running",
        "metadata":{"mode":mode},
    }).execute().data or []
    run_id=created[0]["id"] if created else None
    timings={}

    try:
        refresh_sources(a.earnings_only,a.include_guidance,timings,sec_only=a.sec_only)

        audit=db.rpc("research_data_audit").execute().data or {}
        update={
            "finished_at":datetime.now(timezone.utc).isoformat(),
            "status":"success",
            "metadata":{
                "mode":mode,
                "timings":timings,
                "coverage":{
                    "fundamentals":audit.get("fundamentals"),
                    "earnings":audit.get("earnings"),
                    "valuation":audit.get("valuation"),
                },
                "guidance_enabled":a.include_guidance,
                "financial_audit":financial_audit(started),
            },
        }
        if run_id:
            db.table("pipeline_runs").update(update).eq("id",run_id).execute()
        print(f"\nResearch source refresh completed successfully. timings={timings}")
    except Exception as exc:
        if run_id:
            db.table("pipeline_runs").update({
                "finished_at":datetime.now(timezone.utc).isoformat(),
                "status":"error",
                "error_message":str(exc)[:2000],
                "metadata":{"mode":mode,"timings":timings,"financial_audit":financial_audit(started)},
            }).eq("id",run_id).execute()
        traceback.print_exc()
        raise

if __name__=="__main__":
    main()
