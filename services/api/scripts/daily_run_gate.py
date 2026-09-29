"""Let a backup GitHub schedule run only if today's refresh has not started."""

import os
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))
load_dotenv(API_DIR / ".env")

ISRAEL = ZoneInfo("Asia/Jerusalem")


def should_run(db, event_name, now=None):
    if event_name == "workflow_dispatch":
        return True

    now = now or datetime.now(timezone.utc)
    local_day = now.astimezone(ISRAEL).date()
    # All scheduled triggers start at or after 08:00 Israel time. The buffer
    # tolerates minor scheduler clock drift without matching yesterday's run.
    cutoff = datetime.combine(local_day, time(7, 55), tzinfo=ISRAEL).astimezone(timezone.utc)
    rows = (
        db.table("pipeline_runs")
        .select("id")
        .eq("pipeline", "daily_market_research")
        .gte("started_at", cutoff.isoformat())
        .limit(1)
        .execute()
        .data or []
    )
    return not rows


if __name__ == "__main__":
    from app.db.client import get_supabase

    run = should_run(get_supabase(), os.getenv("GITHUB_EVENT_NAME", ""))
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"run={str(run).lower()}\n")
    print("Starting daily refresh" if run else "Daily refresh already started; skipping duplicate trigger")
