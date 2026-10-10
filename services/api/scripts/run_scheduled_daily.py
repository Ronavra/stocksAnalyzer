"""One gated daily cycle for an independent Windows / server scheduler."""
import os
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from scripts.daily_run_gate import refresh_plan


def run_script(name,args=(),*,required=True):
    try:
        subprocess.run([sys.executable,str(API_DIR/"scripts"/name),*args],check=True,cwd=API_DIR)
    except subprocess.CalledProcessError:
        if required:
            raise
        print(f"WARNING: Optional source step {name} failed. Its pipeline report retains the error; coverage remains incomplete.",file=sys.stderr,flush=True)
        return False
    return True


def main():
    if os.getenv("LOCAL_MARKET_ARCHIVE") and os.getenv("LOCAL_MARKET_ARCHIVE_BACKUP"):
        # Runs even when GitHub completed the market refresh first, or the Data
        # API remains restricted. Direct Postgres is only used for verified cleanup.
        subprocess.run([sys.executable,str(API_DIR/"scripts"/"archive_market_history.py"),
                        "--maintain","--prune"],check=True,cwd=API_DIR)
    db=get_supabase()
    plan=refresh_plan(db,"independent_scheduler")
    if not plan["run_sources"]:
        print("Daily market refresh is active; skipping overlapping work.")
        return
    if plan["run_market"]:
        run_script("run_daily_cycle.py")
    else:
        print("Market refresh already completed; checking source freshness.")
    run_script("validate_daily_cycle.py")
    earnings_ok=True
    try:
        run_script("refresh_research_sources.py",["--earnings-only","--max-age-hours","4"])
        run_script("ingest_massive_earnings.py",["--backfill-missing"])
    except subprocess.CalledProcessError:
        earnings_ok=False
        print("ERROR: Required earnings refresh failed; collecting the remaining sources before reporting failure.",file=sys.stderr,flush=True)
    incomplete=[]
    if os.getenv("SEC_USER_AGENT"):
        if not run_script("refresh_research_sources.py",["--sec-only","--max-age-hours","24"],required=False):
            incomplete.append("SEC fundamentals/valuation")
    else:
        incomplete.append("SEC fundamentals/valuation (SEC_USER_AGENT missing)")
    if not run_script("refresh_analyst_consensus.py",["--max-age-hours","24"],required=False):
        incomplete.append("analyst consensus")
    # Publication still applies its own market/financial freshness gates. A
    # publication failure is required and must not be reported as daily success.
    if earnings_ok:
        run_script("run_weekly_cycle.py")
    if not run_script("refresh_enrichment.py",required=False):
        incomplete.append("news/management guidance")
    if not earnings_ok:
        raise RuntimeError("Required earnings refresh failed; weekly publication blocked. Other sources were refreshed independently.")
    print("Daily market and earnings refresh completed.",flush=True)
    if incomplete:
        print("WARNING: Optional coverage incomplete: "+"; ".join(incomplete),file=sys.stderr,flush=True)


if __name__=="__main__":
    main()
