"""Allow one daily refresh per Israel date unless manually forced."""

import os
import sys
from datetime import datetime, time, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))
load_dotenv(API_DIR / ".env")

ISRAEL = ZoneInfo("Asia/Jerusalem")


def refresh_plan(db, event_name, now=None, force=False):
    if event_name == "workflow_dispatch" and force:
        return {"run_market":True,"run_sources":True}

    now = now or datetime.now(timezone.utc)
    local_day = now.astimezone(ISRAEL).date()
    cutoff = datetime.combine(local_day, time.min, tzinfo=ISRAEL).astimezone(timezone.utc)
    rows = (
        db.table("pipeline_runs")
        .select("id,status,started_at")
        .eq("pipeline", "daily_market_research")
        .gte("started_at", cutoff.isoformat())
        .order("started_at", desc=True)
        .limit(100)
        .execute()
        .data or []
    )
    for row in rows:
        if row.get("status") == "running":
            started = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
            if now - started < timedelta(minutes=195):
                return {"run_market":False,"run_sources":False}
    # Market completion only skips expensive price collection. Other sources
    # have their own completion records and must recover from partial failure.
    market=not any(row.get("status")=="success" for row in rows)
    return {"run_market":market,"run_sources":True}


def should_run(db, event_name, now=None, force=False):
    return refresh_plan(db,event_name,now,force)["run_market"]


if __name__ == "__main__":
    from app.db.client import get_supabase

    plan = refresh_plan(get_supabase(), os.getenv("GITHUB_EVENT_NAME", ""),
                     force=os.getenv("FORCE_DAILY_REFRESH", "false").lower() == "true")
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"run={str(plan['run_market']).lower()}\n")
            fh.write(f"sources={str(plan['run_sources']).lower()}\n")
    print("Starting daily refresh/retry" if plan["run_market"] else
          "Market refresh completed; checking source freshness" if plan["run_sources"] else
          "Market refresh is still active; skipping overlapping work")
