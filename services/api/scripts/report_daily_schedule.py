"""Retain scheduling delays in Actions without failing a valid market update."""
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.research.daily_schedule import schedule_status


def main():
    db=get_supabase()
    rows=(db.table("pipeline_runs").select("status,started_at,finished_at")
          .eq("pipeline","daily_market_research").order("started_at",desc=True).limit(1).execute().data or [])
    status=schedule_status(rows[0] if rows else None)
    print(json.dumps(status))
    if status["overdue"]:
        message="Daily market update has not completed by 12:00 Asia/Jerusalem."
    elif status["late_start"] or status["completed_after_deadline"]:
        message=f"Daily market update started {status['start_delay_minutes']} minutes after 08:00 Asia/Jerusalem; completed after noon: {status['completed_after_deadline']}."
    else:
        message="Daily market update timing is within the monitoring thresholds."
    if status["overdue"] or status["late_start"] or status["completed_after_deadline"]:
        print("::warning::"+message)
    summary=os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary,"a",encoding="utf-8") as file:
            file.write("\nDaily schedule: "+message+"\n")


if __name__=="__main__":
    main()
