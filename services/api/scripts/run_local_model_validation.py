"""Bounded weekly research on the computer holding the verified market archive."""
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.db.market_history import require_full_history


def due(previous, now):
    local=now.astimezone(ZoneInfo("Asia/Jerusalem"))
    saturday=(local-timedelta(days=(local.weekday()-5)%7)).replace(hour=14,minute=0,second=0,microsecond=0)
    if saturday>local:
        saturday-=timedelta(days=7)
    return not any(r.get("status")=="success" and r.get("finished_at") and
                   datetime.fromisoformat(r["finished_at"].replace("Z","+00:00"))>=saturday for r in previous)


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--if-due",action="store_true");args=parser.parse_args()
    db=get_supabase();now=datetime.now(timezone.utc)
    if args.if_due:
        previous=db.table("pipeline_runs").select("status,finished_at").eq("pipeline","local_model_validation").order("started_at",desc=True).limit(5).execute().data or []
        if not due(previous,now):
            print("Local model research already completed for this research week.");return
    claim=db.rpc("claim_local_model_research").execute().data or {}
    if not claim.get("run"):
        print("Local model research is already running.");return
    run={"id":claim["id"]}
    deadline=time.monotonic()+5.5*3600
    try:
        if not os.getenv("LOCAL_MARKET_ARCHIVE"):
            raise RuntimeError("LOCAL_MARKET_ARCHIVE must identify the verified full archive on this computer")
        require_full_history(db)
        db.archive.fingerprint()
        for name in ("validate_daily_cycle.py","repair_financial_coverage.py","ablation_predictive_model.py",
                     "validate_weekly_ranker.py","compare_portfolio_risk.py"):
            subprocess.run([sys.executable,str(API_DIR/"scripts"/name)],cwd=API_DIR,check=True,
                           timeout=max(1,deadline-time.monotonic()))
        db.table("pipeline_runs").update({"status":"success","finished_at":datetime.now(timezone.utc).isoformat(),
            "metadata":{"outcome":"research_completed","forecast_promotion_is_separately_gated":True}}).eq("id",run["id"]).eq("status","running").execute()
    except Exception as exc:
        db.table("pipeline_runs").update({"status":"error","finished_at":datetime.now(timezone.utc).isoformat(),
            "error_message":str(exc)[:500]}).eq("id",run["id"]).eq("status","running").execute()
        raise


if __name__=="__main__": main()
