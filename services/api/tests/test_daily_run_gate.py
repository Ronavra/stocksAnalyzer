from datetime import datetime, timezone

from scripts.daily_run_gate import should_run


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

    def limit(self, *_args):
        return self

    def execute(self):
        matching = [r for r in self.rows if r >= self.cutoff]
        return type("Result", (), {"data": [{"id": 1}] if matching else []})()


class Db:
    def __init__(self, starts):
        self.query = Query(starts)

    def table(self, _name):
        return self.query


def test_backup_skips_when_primary_already_started():
    now = datetime(2026, 9, 29, 5, 17, tzinfo=timezone.utc)
    db = Db([datetime(2026, 9, 29, 5, 1, tzinfo=timezone.utc)])
    assert not should_run(db, "schedule", now)


def test_backup_runs_when_no_attempt_today():
    now = datetime(2026, 9, 29, 5, 17, tzinfo=timezone.utc)
    db = Db([datetime(2026, 9, 28, 5, 1, tzinfo=timezone.utc)])
    assert should_run(db, "schedule", now)


def test_manual_dispatch_can_rerun():
    now = datetime(2026, 9, 29, 5, 17, tzinfo=timezone.utc)
    assert should_run(None, "workflow_dispatch", now)
