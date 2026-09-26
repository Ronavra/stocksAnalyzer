import argparse
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
PIPELINE="research_sources_refresh"

def run(name,*args):
    print(f"\n=== {name} ===",flush=True)
    started=time.monotonic()
    subprocess.run([PY,str(HERE/name),*args],check=True)
    return round(time.monotonic()-started,2)

def recent_success(db,max_age_hours):
    if not max_age_hours:
        return None
    rows=(db.table("pipeline_runs").select("*")
          .eq("pipeline",PIPELINE).eq("status","success")
          .order("finished_at",desc=True).limit(1).execute().data or [])
    if not rows or not rows[0].get("finished_at"):
        return None
    finished=datetime.fromisoformat(rows[0]["finished_at"].replace("Z","+00:00"))
    age=(datetime.now(timezone.utc)-finished).total_seconds()/3600
    return rows[0] if age<=max_age_hours else None

def main():
    ap=argparse.ArgumentParser(description="Refresh non-price research sources with API-safe incremental rules")
    ap.add_argument("--max-age-hours",type=float,default=0,help="Skip the refresh if a successful source refresh is newer than this")
    ap.add_argument("--include-guidance",action="store_true",help="Also sync Massive corporate guidance; disabled by default until plan access is verified")
    a=ap.parse_args()

    db=get_supabase()
    recent=recent_success(db,a.max_age_hours)
    if recent:
        print(f"Research sources already refreshed recently at {recent.get('finished_at')}; skipping duplicate calls.")
        return

    started=datetime.now(timezone.utc).isoformat()
    created=db.table("pipeline_runs").insert({
        "pipeline":PIPELINE,
        "started_at":started,
        "status":"running",
        "metadata":{"mode":"api_safe_incremental"},
    }).execute().data or []
    run_id=created[0]["id"] if created else None
    timings={}

    try:
        # SEC has a 10 req/s fair-access ceiling, not a daily quota.
        # 0.16s pacing stays below the ceiling while refreshing the full universe.
        timings["sec_fundamentals_seconds"]=run(
            "ingest_sec_fundamentals.py","--all","--delay","0.16","--years","10","--quarters","16"
        )
        # Massive is the paid event source. Incremental mode makes one bulk query
        # for records updated since the previous capture instead of ~500 ticker calls.
        timings["massive_earnings_seconds"]=run(
            "ingest_massive_earnings.py","--incremental","--lookback-hours","30"
        )
        if a.include_guidance:
            timings["massive_guidance_seconds"]=run(
                "ingest_massive_guidance.py","--incremental","--lookback-hours","30"
            )

        audit=db.rpc("research_data_audit").execute().data or {}
        update={
            "finished_at":datetime.now(timezone.utc).isoformat(),
            "status":"success",
            "metadata":{
                "mode":"api_safe_incremental",
                "timings":timings,
                "coverage":{
                    "fundamentals":audit.get("fundamentals"),
                    "earnings":audit.get("earnings"),
                    "valuation":audit.get("valuation"),
                },
                "guidance_enabled":a.include_guidance,
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
                "metadata":{"mode":"api_safe_incremental","timings":timings},
            }).eq("id",run_id).execute()
        traceback.print_exc()
        raise

if __name__=="__main__":
    main()
