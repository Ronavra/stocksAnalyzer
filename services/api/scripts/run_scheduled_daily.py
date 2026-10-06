"""One gated daily cycle for an independent Windows / server scheduler."""
import os
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from scripts.daily_run_gate import should_run


def main():
    db=get_supabase()
    if not should_run(db,"independent_scheduler"):
        print("Daily refresh already completed or active; checking Sunday's publication.")
        subprocess.run([sys.executable,str(API_DIR/"scripts"/"run_weekly_cycle.py")],check=True,cwd=API_DIR)
        return
    commands=[("run_daily_cycle.py",[]),("refresh_research_sources.py",["--earnings-only"])]
    if os.getenv("SEC_USER_AGENT"):
        commands.append(("refresh_research_sources.py",["--sec-only"]))
    commands.extend([("refresh_analyst_consensus.py",["--max-age-hours","24"]),
                     ("run_weekly_cycle.py",[]),("refresh_enrichment.py",[])])
    for name,args in commands:
        subprocess.run([sys.executable,str(API_DIR/"scripts"/name),*args],check=True,cwd=API_DIR)


if __name__=="__main__":
    main()
