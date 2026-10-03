import pytest

from scripts import generate_weekly_signals as weekly


class Query:
    def __init__(self, db):
        self.db = db
        self.payload = None

    def select(self, *args):
        return self

    def eq(self, *args):
        return self

    def limit(self, *args):
        return self

    def upsert(self, payload, **kwargs):
        self.payload = payload
        return self

    def execute(self):
        if self.payload is not None:
            self.db.saved.append(self.payload)
            return type("Result", (), {"data": [self.payload]})()
        return type("Result", (), {"data": self.db.existing})()


class Db:
    def __init__(self, rows, existing=None):
        self.rows = rows
        self.existing = existing or []
        self.saved = []

    def rpc(self, name):
        assert name == "research_dashboard_candidates"
        return type("Rpc", (), {"execute": lambda _: type("Result", (), {"data": self.rows})()})()

    def table(self, name):
        assert name == "research_predictions"
        return Query(self)


def candidate(cid, setup_date):
    return {
        "company_id": cid, "ticker": str(cid), "price_date": "2026-09-29",
        "as_of_date": setup_date, "opportunity_score": 95 if cid == 1 else 60,
        "setup_probability_up": .7, "setup_median_return_5d": .02,
        "setup_sample_size": 100, "current_price": 100,
    }


def test_weekly_selection_excludes_old_setup_with_new_price(monkeypatch):
    db = Db([candidate(1, "2026-09-26"), candidate(2, "2026-09-29")])
    monkeypatch.setattr(weekly, "validated_weekly_ranker", lambda *_: None)
    monkeypatch.setattr(weekly, "recent_earnings", lambda *_: {})

    picks = weekly.generate(db, top=2, horizons=(5,))

    assert [ticker for ticker, *_ in picks] == ["2"]
    assert [row["company_id"] for row in db.saved] == [2]
    assert db.saved[0]["entry_price"] is None
    assert db.saved[0]["model_diagnostics"]["entry_policy"] == "next_session_close"


def test_existing_cohort_stays_frozen(monkeypatch):
    db = Db([candidate(2, "2026-09-29")], existing=[{"id": 1}])
    assert weekly.generate(db) == []
    assert db.saved == []


def test_weekly_selection_fails_when_all_setups_are_stale():
    db = Db([candidate(1, "2026-09-26")])
    with pytest.raises(RuntimeError, match="No current setup snapshots"):
        weekly.generate(db)


def test_weekly_ranker_does_not_require_old_rebound_screen(monkeypatch):
    row = candidate(1, "2026-09-29")
    row.update({"setup_probability_up": .3, "setup_sample_size": 10, "setup_median_return_5d": -.03})
    db = Db([row])
    monkeypatch.setattr(weekly, "recent_earnings", lambda *_: {})
    monkeypatch.setattr(weekly, "validated_weekly_ranker", lambda *_: {
        "finished_at": "2026-09-29", "results": {"selected_variant": "expected_excess"}})
    monkeypatch.setattr(weekly, "current_predictions", lambda *_: {1: {
        "rank_score": .02, "expected_excess": .02, "expected_return": .025, "downside_p10": -.04, "feature_coverage": 1.}})
    assert len(weekly.generate(db, horizons=(5,))) == 1
    assert db.saved[0]["model_diagnostics"]["ranking_mode"] == "weekly_top_five"
    assert db.saved[0]["model_probability_up"] is None
