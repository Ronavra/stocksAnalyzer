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

    assert calls == ["refresh_free_earnings.py", "ingest_sec_fundamentals.py"]
    assert timings == {"free_earnings_seconds": 1.25}


def test_weekly_earnings_refresh_does_not_call_sec(monkeypatch):
    calls = []

    def fake_run(name, *args):
        calls.append(name)
        return 2

    monkeypatch.setattr(refresh, "run", fake_run)
    timings = {}
    refresh.refresh_sources(True, False, timings)

    assert calls == ["refresh_free_earnings.py"]
    assert timings == {"free_earnings_seconds": 2}


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


def test_reusing_sec_filings_still_rebuilds_valuation_for_latest_close(monkeypatch):
    monkeypatch.setattr(refresh.sys,"argv",["refresh","--sec-only","--max-age-hours","24"])
    monkeypatch.setattr(refresh,"get_supabase",lambda:object())
    monkeypatch.setattr(refresh,"recent_success",lambda *args:{"finished_at":"recent"})
    calls=[]
    monkeypatch.setattr(refresh,"run",lambda *args:calls.append(args))
    refresh.main()
    assert calls==[("build_daily_valuation.py",)]


def test_paid_success_does_not_skip_first_free_refresh(monkeypatch):
    monkeypatch.setattr(refresh.sys,'argv',['refresh','--earnings-only','--max-age-hours','4'])
    class Query:
        def insert(self,*a,**kw): return self
        def update(self,*a,**kw): return self
        def eq(self,*a): return self
        def execute(self): return type('Result',(),{'data':[{'id':1}]})()
    class Db:
        def table(self,*a): return Query()
        def rpc(self,*a):
            return type('Result',(),{'execute':lambda self:type('Response',(),{'data':{}})()})()
    monkeypatch.setattr(refresh,'get_supabase',lambda:Db())
    monkeypatch.setattr(refresh,'recent_success',lambda *a:{'finished_at':'recent','metadata':{'timings':{'massive_earnings_seconds':1}}})
    calls=[]
    monkeypatch.setattr(refresh,'run',lambda *a:calls.append(a) or 1)
    monkeypatch.setattr(refresh,'financial_audit',lambda *a:None)
    refresh.main()
    assert calls==[('refresh_free_earnings.py',)]


def test_earnings_recency_does_not_reuse_a_pre_close_refresh(monkeypatch):
    from datetime import datetime, timezone
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None): return cls(2026,10,21,20,30,tzinfo=timezone.utc)
    monkeypatch.setattr(refresh,'datetime',Clock)
    class Query:
        def select(self,*a): return self
        def eq(self,*a): return self
        def order(self,*a,**kw): return self
        def limit(self,*a): return self
        def execute(self): return type('Result',(),{'data':[{'status':'success','started_at':'2026-10-21T19:00:00Z','finished_at':'2026-10-21T20:10:00Z'}]})()
    class Db:
        def table(self,*a): return Query()
    assert refresh.recent_success(Db(),4,refresh.EARNINGS_PIPELINE) is None
    assert refresh.recent_success(Db(),4,refresh.FULL_PIPELINE) is not None
