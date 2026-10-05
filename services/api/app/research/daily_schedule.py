"""Report daily timeliness separately from successful data validation."""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

ISRAEL=ZoneInfo("Asia/Jerusalem")


def schedule_status(run, now=None):
    now=(now or datetime.now(timezone.utc)).astimezone(ISRAEL)
    due=datetime.combine(now.date(),time(8),tzinfo=ISRAEL)
    deadline=datetime.combine(now.date(),time(12),tzinfo=ISRAEL)
    run=run or {}
    def timestamp(key):
        try:
            value=datetime.fromisoformat(run[key].replace("Z","+00:00"))
            if value.tzinfo is None:
                return None
            local=value.astimezone(ISRAEL)
            return local if local.date()==now.date() and local<=now else None
        except (KeyError,AttributeError,TypeError,ValueError):
            return None
    started=timestamp("started_at")
    finished=timestamp("finished_at")
    completed=run.get("status")=="success" and started is not None and finished is not None and finished>=started
    delay=max(0,int((started-due).total_seconds()/60)) if started else None
    return {"timezone":"Asia/Jerusalem","time":"08:00","scheduled_at":due.isoformat(),
            "completion_deadline":deadline.isoformat(),"started_at":started.isoformat() if started else None,
            "start_delay_minutes":delay,"late_start":delay is not None and delay>60,
            "completed_after_deadline":bool(completed and finished>deadline),
            "overdue":now>=deadline and not completed,"exact_start_guaranteed":False}
