import pytest

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
