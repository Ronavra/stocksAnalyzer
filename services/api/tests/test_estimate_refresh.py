from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import pytest
from scripts.refresh_estimate_snapshots import refresh


class Db:
    def __init__(self):
        self.snapshots = []; self.runs = []; self.fail_write = False
    def table(self, name):
        db = self
        class Query:
            def __init__(self):
                self.filters = []; self.action = None
            def select(self, *args): return self
            def eq(self, key, value): self.filters.append((key, value)); return self
            def order(self, *args, **kwargs): return self
            def range(self, *args): return self
            def insert(self, row): self.action = ("insert", row); return self
            def update(self, row): self.action = ("update", row); return self
            def upsert(self, rows, **kwargs):
                assert kwargs["ignore_duplicates"] is True
                self.action = ("upsert", rows); return self
            def execute(self):
                if self.action:
                    operation, value = self.action
                    if operation == "insert":
                        db.runs.append(dict(value, id=len(db.runs)+1))
                        return SimpleNamespace(data=[db.runs[-1]])
                    if operation == "update":
                        db.runs[-1].update(value)
                        return SimpleNamespace(data=[])
                    if db.fail_write: raise RuntimeError("DB unavailable")
                    db.snapshots.extend(value)
                    return SimpleNamespace(data=[])
                if name == "companies": return SimpleNamespace(data=[{"id": 1, "ticker": "AAA"}, {"id": 2, "ticker": "BBB"}])
                rows = [r for r in db.snapshots if all(r.get(k) == v for k, v in self.filters)]
                return SimpleNamespace(data=rows)
        return Query()


class Provider:
    source = "yahoo_finance"
    def __init__(self): self.calls = []
    def fetch(self, ticker):
        self.calls.append(ticker)
        if ticker == "BBB": return []
        return [{"period": "0y", "endDate": (datetime.now(timezone.utc).date()+timedelta(days=100)).isoformat(), "earningsEstimate": {"avg": {"raw": 0}}}]


def test_daily_retry_keeps_first_snapshot_and_reports_empty_company():
    db, provider = Db(), Provider()
    first = refresh(db, provider, delay=0)
    captured = db.snapshots[0]["captured_at"]
    second = refresh(db, provider, delay=0)
    assert first["coverage_status"] == second["coverage_status"] == "partial"
    assert provider.calls == ["AAA", "BBB", "BBB"]
    assert len(db.snapshots) == 1 and db.snapshots[0]["captured_at"] == captured
    assert second["reused"] == 1 and second["empty_tickers"] == ["BBB"]


def test_provider_errors_and_unattempted_budget_are_not_success():
    class Blocked(Provider):
        def fetch(self, ticker): raise RuntimeError("sensitive URL")
    db = Db()
    with pytest.raises(RuntimeError, match="incomplete"):
        refresh(db, Blocked(), delay=0, limit=1)
    assert db.runs[-1]["status"] == "error" and db.snapshots == []
    report = db.runs[-1]["metadata"]
    assert report["unattempted"] == 1
    assert report["errors"] == [{"ticker": "AAA", "type": "RuntimeError"}]


def test_database_failure_aborts_and_is_not_an_empty_provider_result():
    db = Db(); db.fail_write = True
    provider = Provider()
    with pytest.raises(RuntimeError, match="DB unavailable"):
        refresh(db, provider, delay=0)
    assert provider.calls == ["AAA"]
    assert db.runs[-1]["status"] == "error"
    assert db.runs[-1]["metadata"]["errors"] == []
