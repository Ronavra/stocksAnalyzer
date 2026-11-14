from datetime import datetime, timezone
from app.research.daily_schedule import schedule_status


def at(value):
    return datetime.fromisoformat(value)


def test_successful_late_run_retains_delay_after_completion():
    run={"status":"success","started_at":"2026-10-06T12:08:01Z","finished_at":"2026-10-06T12:25:15Z"}
    result=schedule_status(run,at("2026-10-06T17:00:00+00:00"))
    assert result["start_delay_minutes"]==428
    assert result["late_start"] and result["completed_after_deadline"]
    assert not result["overdue"]


def test_missing_failed_and_running_updates_are_overdue_after_noon():
    now=at("2026-10-06T09:00:00+00:00")
    for run in (None,{"status":"running","started_at":"2026-10-06T05:00:00Z"},
                {"status":"error","started_at":"2026-10-06T05:00:00Z","finished_at":"2026-10-06T06:00:00Z"},
                {"status":"success","started_at":"2026-10-04T05:00:00Z","finished_at":"2026-10-04T06:00:00Z"}):
        assert schedule_status(run,now)["overdue"]
    assert not schedule_status(None,at("2026-10-06T08:59:59+00:00"))["overdue"]


def test_israel_day_and_dst_are_used_for_schedule():
    # Winter UTC+2; summer UTC+3. UTC midnight is not the daily boundary.
    for day,start,now in (("2026-10-05","2026-10-06T05:00:00Z","2026-10-06T06:00:00Z"),
                           ("2026-11-05","2026-11-05T06:00:00Z","2026-11-05T07:00:00Z")):
        result=schedule_status({"status":"success","started_at":start,"finished_at":now},at(now))
        assert result["scheduled_at"].startswith(day+"T08:00")
        assert result["start_delay_minutes"]==0 and not result["late_start"]
    assert schedule_status(None,at("2026-10-05T22:00:00+00:00"))["scheduled_at"].startswith("2026-10-06")


def test_invalid_naive_future_and_reversed_timestamps_do_not_certify_success():
    now=at("2026-10-06T17:00:00+00:00")
    for started,finished in (("invalid",None),("2026-10-05T05:00:00","2026-10-05T06:00:00"),
                             ("2026-10-06T19:00:00Z","2026-10-06T20:00:00Z"),
                             ("2026-10-06T08:00:00Z","2026-10-06T07:00:00Z")):
        assert schedule_status({"status":"success","started_at":started,"finished_at":finished},now)["overdue"]


def test_non_session_days_do_not_trigger_false_deadline_alerts():
    # Friday's NYSE session becomes available on Saturday morning in Israel.
    saturday=schedule_status(None,at("2026-11-14T10:30:00Z"))
    assert saturday["market_session_due"] and saturday["overdue"]
    assert saturday["expected_market_date"]=="2026-11-13"

    # No fresh NYSE session is due on Sunday or Monday mornings in Israel.
    for instant in ("2026-11-15T10:30:00Z","2026-11-16T10:30:00Z"):
        status=schedule_status(None,at(instant))
        assert not status["market_session_due"]
        assert not status["overdue"]
        assert status["expected_market_date"]=="2026-11-13"


def test_us_market_holiday_does_not_create_missing_refresh():
    # US Thanksgiving is Thursday: no new session is due Friday morning
    # Israel time, whereas Saturday morning follows the Friday session.
    friday=schedule_status(None,at("2026-11-27T10:30:00Z"))
    saturday=schedule_status(None,at("2026-11-28T10:30:00Z"))
    assert friday["expected_market_date"]=="2026-11-25"
    assert not friday["market_session_due"] and not friday["overdue"]
    assert saturday["market_session_due"] and saturday["overdue"]
