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


def should_run(db, event_name, now=None, force=False):
    if event_name == "workflow_dispatch" and force:
        return True

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
        if row.get("status") == "success":
            return False
        if row.get("status") == "running":
            started = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
            if now - started < timedelta(minutes=195):
                return False
    return True


if __name__ == "__main__":
    from app.db.client import get_supabase

    run = should_run(get_supabase(), os.getenv("GITHUB_EVENT_NAME", ""),
                     force=os.getenv("FORCE_DAILY_REFRESH", "false").lower() == "true")
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"run={str(run).lower()}\n")
    print("Starting daily refresh/retry" if run else "Daily refresh succeeded or is still active today; skipping duplicate trigger")
