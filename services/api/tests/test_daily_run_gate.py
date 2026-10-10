from datetime import datetime, timezone

from scripts.daily_run_gate import should_run, refresh_plan


class Query:
    def __init__(self, rows):
        self.rows = rows
        self.cutoff = None

    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def gte(self, _field, cutoff):
        self.cutoff = datetime.fromisoformat(cutoff)
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        matching=[r for r in self.rows if datetime.fromisoformat(r["started_at"])>=self.cutoff]
        return type("Result", (), {"data": matching})()


class Db:
    def __init__(self, starts):
        self.query = Query([{ "id":1,"started_at":r.isoformat(),"status":"success"} if isinstance(r,datetime) else r for r in starts])

    def table(self, _name):
        return self.query


def test_schedule_skips_when_daily_already_started():
    now = datetime(2026, 9, 29, 5, 17, tzinfo=timezone.utc)
    db = Db([datetime(2026, 9, 29, 5, 1, tzinfo=timezone.utc)])
    assert not should_run(db, "schedule", now)


def test_schedule_runs_when_no_attempt_today():
    now = datetime(2026, 9, 29, 5, 17, tzinfo=timezone.utc)
    db = Db([datetime(2026, 9, 28, 5, 1, tzinfo=timezone.utc)])
    assert should_run(db, "schedule", now)


def test_manual_dispatch_skips_after_daily_started():
    now = datetime(2026, 9, 29, 5, 17, tzinfo=timezone.utc)
    db = Db([datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc)])
    assert not should_run(db, "workflow_dispatch", now)


def test_manual_dispatch_can_force_an_explicit_rerun():
    now = datetime(2026, 9, 29, 5, 17, tzinfo=timezone.utc)
    assert should_run(None, "workflow_dispatch", now, force=True)


def test_early_manual_run_is_counted_on_same_israel_day():
    now = datetime(2026, 9, 29, 5, 17, tzinfo=timezone.utc)
    db = Db([datetime(2026, 9, 28, 22, 30, tzinfo=timezone.utc)])
    assert not should_run(db, "schedule", now)


def test_failed_attempt_can_retry():
    now=datetime(2026,9,29,8,tzinfo=timezone.utc)
    assert should_run(Db([{"started_at":"2026-09-29T05:00:00+00:00","status":"error"}]),"schedule",now)


def test_running_attempt_blocks_until_workflow_timeout():
    now=datetime(2026,9,29,8,tzinfo=timezone.utc)
    assert not should_run(Db([{"started_at":"2026-09-29T05:00:00+00:00","status":"running"}]),"schedule",now)
    assert should_run(Db([{"started_at":"2026-09-29T04:00:00+00:00","status":"running"}]),"schedule",now)


def test_later_failure_cannot_hide_successful_attempt():
    now=datetime(2026,9,29,8,tzinfo=timezone.utc)
    assert not should_run(Db([{"started_at":"2026-09-29T06:00:00+00:00","status":"error"},
                             {"started_at":"2026-09-29T05:00:00+00:00","status":"success"}]),"schedule",now)


def test_completed_prices_do_not_skip_failed_or_missing_source_refreshes():
    now=datetime(2026,9,29,8,tzinfo=timezone.utc)
    plan=refresh_plan(Db([datetime(2026,9,29,5,tzinfo=timezone.utc)]),"schedule",now)
    assert plan=={"run_market":False,"run_sources":True}


def test_active_forced_market_run_blocks_sources_even_after_earlier_success():
    now=datetime(2026,9,29,8,tzinfo=timezone.utc)
    rows=[{"started_at":"2026-09-29T05:00:00+00:00","status":"success"},
          {"started_at":"2026-09-29T07:00:00+00:00","status":"running"}]
    assert refresh_plan(Db(rows),"schedule",now)=={"run_market":False,"run_sources":False}
