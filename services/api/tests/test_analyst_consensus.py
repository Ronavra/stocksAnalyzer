from datetime import datetime,timezone,timedelta
import pytest
from app.research.analyst_consensus import consensus_score
from app.providers.analyst_consensus import normalize
from scripts import refresh_analyst_consensus as ingest

NOW=datetime(2026,10,3,12,tzinfo=timezone.utc)


def snapshot(**changes):
    return {"company_id":1,"source":"yahoo_finance","observed_at":"2026-10-03T11:00:00Z","period_date":"2026-10-01",
            "strong_buy":10,"buy":0,"hold":0,"sell":0,"strong_sell":0,**changes}


def score(rows,**kwargs):
    return consensus_score(rows,"2026-10-02",now=NOW,**kwargs)


def test_neutral_missing_stale_and_small_groups_do_not_redistribute_weight():
    assert score([])["score"]==50
    for row,reason in [(snapshot(observed_at="2026-09-20T11:00:00Z",period_date="2026-09-01"),"stale_capture"),
                       (snapshot(period_date="2026-08-01"),"stale_provider_period"),
                       (snapshot(strong_buy=2),"insufficient_analysts")]:
        result=score([row])
        assert result["score"]==50 and not result["available"] and result["status"]==reason


def test_consensus_direction_and_small_sample_shrinkage():
    buy=score([snapshot()]); sell=score([snapshot(strong_buy=0,strong_sell=10)])
    large=score([snapshot(strong_buy=100)])
    assert 50<buy["score"]<large["score"]<100
    assert sell["score"]<50 and buy["analyst_count"]==10
    assert score([snapshot(strong_buy=0,hold=10)])["score"]==50


def test_future_capture_and_historical_backfill_never_enter_a_past_selection():
    assert not score([snapshot(observed_at="2026-10-03T13:00:00Z")])["available"]
    assert not score([snapshot(period_date="2026-09-01")],live=False)["available"]
    known=snapshot(period_date="2026-09-01",observed_at="2026-10-02T19:00:00Z")
    assert score([known],live=False)["available"]
    after_close={**known,"observed_at":"2026-10-02T21:00:00Z"}
    assert not score([after_close],live=False)["available"]


def test_latest_invalid_revision_does_not_revive_an_older_buy_consensus():
    latest=snapshot(strong_buy=-1,observed_at="2026-10-03T11:30:00Z")
    result=score([snapshot(),latest])
    assert result["score"]==50 and result["status"]=="invalid_counts"


def test_normalizer_distinguishes_provider_month_capture_and_targets():
    rows=normalize(1,[{"period":"0m","strongBuy":10,"buy":2,"hold":3,"sell":0,"strongSell":0},
                      {"period":"-1m","strongBuy":8,"buy":2,"hold":3,"sell":0,"strongSell":0}],
                   "yahoo_finance","2026-10-03T11:00:00Z",{"mean":100,"low":80,"high":120})
    assert [r["period_date"] for r in rows]==["2026-10-01","2026-09-01"]
    assert rows[0]["target_mean"]==100 and "target_mean" not in rows[1]
    assert rows[1]["observed_at"]=="2026-10-03T11:00:00Z"
    assert normalize(1,[{"period":"0m","strongBuy":10}],"yahoo_finance","2026-10-03T11:00:00Z")==[]


class Db:
    def __init__(self):
        self.snapshots=[]; self.runs=[]
    def table(self,name):
        db=self
        class Query:
            data=[]
            def select(self,*args):return self
            def eq(self,*args):return self
            def gte(self,*args):return self
            def order(self,*args,**kwargs):return self
            def range(self,*args):return self
            def execute(self):
                if name=="companies":self.data=[{"id":1,"ticker":"AAA"},{"id":2,"ticker":"BBB"}]
                elif name=="analyst_consensus_snapshots":self.data=db.snapshots
                return self
            def insert(self,rows):
                if name=="analyst_consensus_snapshots":db.snapshots.extend(rows)
                else:
                    db.runs.append(rows);self.data=[{"id":len(db.runs)}]
                return self
            def update(self,row):db.runs[-1].update(row);return self
        return Query()


def test_collection_reuses_fresh_companies_and_keeps_partial_coverage_visible(monkeypatch,tmp_path):
    monkeypatch.setattr(ingest,"API_DIR",tmp_path)
    class Provider:
        source="yahoo_finance"
        calls=0
        def fetch(self,ticker):
            self.calls+=1
            if ticker=="BBB":return [],None
            return [{"period":"0m","strongBuy":10,"buy":0,"hold":0,"sell":0,"strongSell":0}],None
    db=Db();provider=Provider()
    first=ingest.refresh(db,provider,delay=0)
    captured=db.snapshots[0]["observed_at"]
    second=ingest.refresh(db,provider,delay=0)
    assert first["coverage_status"]==second["coverage_status"]=="partial"
    assert first["current_companies"]==1 and second["reused"]==1
    assert len(db.snapshots)==1 and db.snapshots[0]["observed_at"]==captured
    assert provider.calls==3


def test_blocked_provider_is_reported_without_fabricating_data(monkeypatch,tmp_path):
    monkeypatch.setattr(ingest,"API_DIR",tmp_path)
    class Provider:
        source="yahoo_finance"
        def fetch(self,ticker):raise RuntimeError("blocked")
    db=Db()
    with pytest.raises(RuntimeError,match="No usable"):
        ingest.refresh(db,Provider(),delay=0)
    assert db.snapshots==[] and db.runs[-1]["status"]=="error"
    assert db.runs[-1]["metadata"]["current_companies"]==0


def test_cache_does_not_treat_an_older_month_as_current_usable_coverage(monkeypatch,tmp_path):
    monkeypatch.setattr(ingest,"API_DIR",tmp_path)
    now=datetime.now(timezone.utc)
    current=now.date().replace(day=1)
    previous=(current-timedelta(days=1)).replace(day=1)
    db=Db()
    db.snapshots=[snapshot(observed_at=now.isoformat(),period_date=current.isoformat(),strong_buy=2),
                  snapshot(observed_at=now.isoformat(),period_date=previous.isoformat(),strong_buy=10)]
    class Provider:
        source="yahoo_finance"
        def fetch(self,ticker):return [],None
    with pytest.raises(RuntimeError,match="No usable"):
        ingest.refresh(db,Provider(),delay=0)
    assert db.runs[-1]["metadata"]["reused"]==0
    assert db.runs[-1]["metadata"]["current_companies"]==0
