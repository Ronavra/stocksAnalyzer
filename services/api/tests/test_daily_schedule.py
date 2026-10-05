from datetime import datetime, timezone
from app.research.daily_schedule import schedule_status


def at(value):
    return datetime.fromisoformat(value)


def test_successful_late_run_retains_delay_after_completion():
    run={"status":"success","started_at":"2026-10-05T12:08:01Z","finished_at":"2026-10-05T12:25:15Z"}
    result=schedule_status(run,at("2026-10-05T17:00:00+00:00"))
    assert result["start_delay_minutes"]==428
    assert result["late_start"] and result["completed_after_deadline"]
    assert not result["overdue"]


def test_missing_failed_and_running_updates_are_overdue_after_noon():
    now=at("2026-10-05T09:00:00+00:00")
    for run in (None,{"status":"running","started_at":"2026-10-05T05:00:00Z"},
                {"status":"error","started_at":"2026-10-05T05:00:00Z","finished_at":"2026-10-05T06:00:00Z"},
                {"status":"success","started_at":"2026-10-04T05:00:00Z","finished_at":"2026-10-04T06:00:00Z"}):
        assert schedule_status(run,now)["overdue"]
    assert not schedule_status(None,at("2026-10-05T08:59:59+00:00"))["overdue"]


def test_israel_day_and_dst_are_used_for_schedule():
    # Winter UTC+2; summer UTC+3. UTC midnight is not the daily boundary.
    for day,start,now in (("2026-10-05","2026-10-05T05:00:00Z","2026-10-05T06:00:00Z"),
                           ("2026-11-05","2026-11-05T06:00:00Z","2026-11-05T07:00:00Z")):
        result=schedule_status({"status":"success","started_at":start,"finished_at":now},at(now))
        assert result["scheduled_at"].startswith(day+"T08:00")
        assert result["start_delay_minutes"]==0 and not result["late_start"]
    assert schedule_status(None,at("2026-10-05T22:00:00+00:00"))["scheduled_at"].startswith("2026-10-06")


def test_invalid_naive_future_and_reversed_timestamps_do_not_certify_success():
    now=at("2026-10-05T17:00:00+00:00")
    for started,finished in (("invalid",None),("2026-10-05T05:00:00","2026-10-05T06:00:00"),
                             ("2026-10-05T19:00:00Z","2026-10-05T20:00:00Z"),
                             ("2026-10-05T08:00:00Z","2026-10-05T07:00:00Z")):
        assert schedule_status({"status":"success","started_at":started,"finished_at":finished},now)["overdue"]
