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

    def insert(self,payload):
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
        assert name in ("research_predictions","pipeline_runs")
        return Query(self)


def candidate(cid, setup_date):
    return {
        "company_id": cid, "ticker": str(cid), "price_date": "2026-09-29",
        "as_of_date": setup_date, "opportunity_score": 95 if cid == 1 else 60,
        "setup_probability_up": .7, "setup_median_return_5d": .02,
        "setup_sample_size": 100, "current_price": 100,
    }


def mock_finance(monkeypatch,eligible=True):
    monkeypatch.setattr(weekly,"load_inputs",lambda *_:{})
    def rank(rows,*args,**kwargs):
        picks=[{"row":row,"score":70.,"financial":{"score":80.,"coverage":1.,"period_end":"2026-06-30"},
                "contributions":{"financial":36.,"technical":24.,"analyst":5.,"earnings":5.},"analyst":{"score":50.,"available":False,"status":"missing"},
                "technical_score":62.5,"earnings_score":50.,"earnings_available":False,"catalyst":{}}
               for row in rows] if eligible else []
        return picks,{"policy_version":"financial-analyst-priority-v2","decision_at":"2026-09-30T12:00:00Z","weights":{"financial":.45,"technical":.35,"analyst":.1,"earnings":.1}}
    monkeypatch.setattr(weekly,"rank_candidates",rank)


def test_weekly_selection_excludes_old_setup_with_new_price(monkeypatch):
    db = Db([candidate(1, "2026-09-26"), candidate(2, "2026-09-29")])
    mock_finance(monkeypatch)
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


def test_financial_policy_is_recorded_without_a_validated_forecast(monkeypatch):
    row = candidate(1, "2026-09-29")
    row.update({"setup_probability_up": .3, "setup_sample_size": 100, "setup_median_return_5d": -.03})
    db = Db([row])
    monkeypatch.setattr(weekly, "recent_earnings", lambda *_: {})
    mock_finance(monkeypatch)
    assert len(weekly.generate(db, horizons=(5,))) == 1
    assert db.saved[0]["model_diagnostics"]["ranking_mode"] == "financial_priority"
    assert db.saved[0]["model_diagnostics"]["financial_ranking"]["weights"]=={"financial":.45,"technical":.35,"analyst":.1,"earnings":.1}
    assert db.saved[0]["model_probability_up"] is None
    assert db.saved[0]["model_expected_return"] is None


def test_no_financially_eligible_stocks_does_not_pad_the_shortlist(monkeypatch):
    db=Db([candidate(1,"2026-09-29")])
    monkeypatch.setattr(weekly,"recent_earnings",lambda *_:{})
    mock_finance(monkeypatch,eligible=False)
    assert weekly.generate(db,horizons=(5,))==[]
    assert db.saved==[]


def test_dry_run_never_changes_frozen_predictions(monkeypatch):
    db=Db([candidate(1,"2026-09-29")],existing=[{"id":1}])
    monkeypatch.setattr(weekly,"recent_earnings",lambda *_:{})
    mock_finance(monkeypatch)
    assert len(weekly.generate(db,horizons=(5,),dry_run=True))==1
    assert db.saved==[]
