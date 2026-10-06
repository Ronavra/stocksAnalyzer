import pytest
from datetime import date

from scripts import run_weekly_cycle


class Db:
    def __init__(self, run, candidates):
        self.run=run
        self.candidates=candidates

    def table(self,name):
        assert name=="pipeline_runs"
        return Query([self.run] if self.run else [])

    def rpc(self,name):
        assert name=="research_dashboard_candidates"
        return Query(self.candidates)


class Query:
    def __init__(self,data):
        self.data=data

    def select(self,*args): return self
    def eq(self,*args): return self
    def order(self,*args,**kwargs): return self
    def limit(self,*args): return self
    def execute(self): return self


def health(day="2026-10-02",ok=True):
    return {"ok":ok,"error_message":"Missing Friday close" if not ok else None,
            "expected_market_date":day}


def successful_run(day="2026-10-02"):
    return {"status":"success","expected_market_date":day,
            "latest_price_date":day,"latest_feature_date":day}


def test_weekly_freeze_needs_fully_validated_friday_close(monkeypatch):
    monkeypatch.setattr(run_weekly_cycle,"validate",lambda db:health())
    stale=Db(successful_run("2026-10-01"),[{"price_date":"2026-10-01","as_of_date":"2026-10-01"}])
    with pytest.raises(RuntimeError,match="has not validated"):
        run_weekly_cycle.check_readiness(stale)

    failed=Db({**successful_run(),"status":"error"},[{"price_date":"2026-10-02","as_of_date":"2026-10-02"}])
    with pytest.raises(RuntimeError,match="has not validated"):
        run_weekly_cycle.check_readiness(failed)


def test_weekly_freeze_needs_matching_setups_and_full_coverage(monkeypatch):
    monkeypatch.setattr(run_weekly_cycle,"validate",lambda db:health(ok=False))
    with pytest.raises(RuntimeError,match="Missing Friday close"):
        run_weekly_cycle.check_readiness(Db(successful_run(),[]))

    monkeypatch.setattr(run_weekly_cycle,"validate",lambda db:health())
    with pytest.raises(RuntimeError,match="No current setup snapshots"):
        run_weekly_cycle.check_readiness(Db(successful_run(),[{"price_date":"2026-10-02","as_of_date":"2026-10-01"}]))

    assert run_weekly_cycle.check_readiness(Db(successful_run(),[{"price_date":"2026-10-02","as_of_date":"2026-10-02"}]))=="2026-10-02"


def test_weekly_cycle_skips_readiness_and_evaluation_when_not_due(monkeypatch):
    monkeypatch.setattr(run_weekly_cycle,"get_supabase",lambda:object())
    monkeypatch.setattr(run_weekly_cycle,"latest_expected_market_date",lambda:date(2026,10,9))
    monkeypatch.setattr(run_weekly_cycle,"publication_due",lambda *args:False)
    monkeypatch.setattr(run_weekly_cycle,"check_readiness",lambda *args:pytest.fail("Not due: must skip readiness"))
    monkeypatch.setattr(run_weekly_cycle,"run",lambda *args:pytest.fail("Not due: must skip publication"))
    run_weekly_cycle.main()


def test_due_sunday_requires_readiness_before_publication(monkeypatch):
    monkeypatch.setattr(run_weekly_cycle,"get_supabase",lambda:object())
    monkeypatch.setattr(run_weekly_cycle,"latest_expected_market_date",lambda:date(2026,10,9))
    monkeypatch.setattr(run_weekly_cycle,"publication_due",lambda *args:True)
    def unready(db):
        raise RuntimeError("Friday refresh incomplete")
    monkeypatch.setattr(run_weekly_cycle,"check_readiness",unready)
    monkeypatch.setattr(run_weekly_cycle,"run",lambda *args:pytest.fail("Unready: must not publish"))
    with pytest.raises(RuntimeError,match="refresh incomplete"):
        run_weekly_cycle.main()


def test_ready_sunday_requests_five_stocks_once_with_all_horizons(monkeypatch):
    monkeypatch.setattr(run_weekly_cycle,"get_supabase",lambda:object())
    monkeypatch.setattr(run_weekly_cycle,"latest_expected_market_date",lambda:date(2026,10,9))
    monkeypatch.setattr(run_weekly_cycle,"publication_due",lambda *args:True)
    monkeypatch.setattr(run_weekly_cycle,"check_readiness",lambda db:"2026-10-09")
    calls=[]
    monkeypatch.setattr(run_weekly_cycle,"run",lambda *args:calls.append(args))
    run_weekly_cycle.main()
    assert calls==[("evaluate_signals.py",),("generate_weekly_signals.py","--top","5","--horizons","5","10","20")]
