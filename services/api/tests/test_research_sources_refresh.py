import subprocess

import pytest

from scripts import refresh_research_sources as refresh


def test_full_refresh_persists_earnings_timing_before_sec_denial(monkeypatch):
    calls = []

    def fake_run(name, *args):
        calls.append(name)
        if name == "ingest_sec_fundamentals.py":
            raise subprocess.CalledProcessError(1, name)
        return 1.25

    monkeypatch.setattr(refresh, "run", fake_run)
    timings = {}
    with pytest.raises(subprocess.CalledProcessError):
        refresh.refresh_sources(False, False, timings)

    assert calls == ["ingest_massive_earnings.py", "ingest_sec_fundamentals.py"]
    assert timings == {"massive_earnings_seconds": 1.25}


def test_weekly_earnings_refresh_does_not_call_sec(monkeypatch):
    calls = []

    def fake_run(name, *args):
        calls.append(name)
        return 2

    monkeypatch.setattr(refresh, "run", fake_run)
    timings = {}
    refresh.refresh_sources(True, False, timings)

    assert calls == ["ingest_massive_earnings.py"]
    assert timings == {"massive_earnings_seconds": 2}


def test_sec_only_refresh_does_not_fetch_earnings_again(monkeypatch):
    calls = []

    def fake_run(name, *args):
        calls.append(name)
        return 3

    monkeypatch.setattr(refresh, "run", fake_run)
    timings = {}
    refresh.refresh_sources(False, False, timings, sec_only=True)

    assert calls == ["ingest_sec_fundamentals.py", "build_daily_valuation.py"]
    assert timings == {"sec_fundamentals_seconds": 3, "valuation_seconds": 3}


def test_recency_checks_the_selected_pipeline():
    queried = []

    class Query:
        data = []

        def select(self, *args, **kwargs):
            return self

        def eq(self, key, value):
            queried.append((key, value))
            return self

        def order(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def execute(self):
            return self

    class Db:
        def table(self, name):
            assert name == "pipeline_runs"
            return Query()

    refresh.recent_success(Db(), 4, refresh.EARNINGS_PIPELINE)
    assert ("pipeline", "earnings_refresh") in queried


def test_later_failure_is_retried_even_when_a_prior_success_is_recent():
    from datetime import datetime,timezone
    now=datetime.now(timezone.utc).isoformat()
    class Query:
        def select(self,*args): return self
        def eq(self,key,value):
            assert (key,value)==("pipeline",refresh.EARNINGS_PIPELINE)
            return self
        def order(self,*args,**kwargs): return self
        def limit(self,*args): return self
        def execute(self):
            return type("Result",(),{"data":[{"status":"error","finished_at":now}]})()
    class Db:
        def table(self,*args): return Query()
    assert refresh.recent_success(Db(),4,refresh.EARNINGS_PIPELINE) is None
