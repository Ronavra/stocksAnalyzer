import asyncio
from scripts import ingest_massive_earnings as ingest


def event(ticker="ABC",date="2026-10-08",updated="2026-10-09T12:00:00Z",**values):
    return {"ticker":ticker,"date":date,"last_updated":updated,"benzinga_id":"event-1",**values}


def test_latest_provider_revision_wins_independently_of_page_order():
    older=event(actual_eps=1,estimated_eps=.8)
    newer=event(updated="2026-10-09T15:00:00+02:00",actual_eps=2,estimated_eps=1.5)
    expected=ingest.unique_payload([older,newer],{"ABC":1},"capture")
    assert ingest.unique_payload([newer,older],{"ABC":1},"capture")==expected
    payload,ignored,duplicates=expected
    assert len(payload)==1 and ignored==0 and duplicates==1
    assert payload[0]["reported_eps"]==2
    assert payload[0]["surprise"]==.5


def test_new_revision_can_remove_a_value_without_reviving_older_data():
    payload,_,_=ingest.unique_payload([event(actual_eps=1),
        event(updated="2026-10-10T12:00:00Z",actual_eps=None)],{"ABC":1},"capture")
    assert payload[0]["reported_eps"] is None


def test_equal_revision_prefers_complete_row_without_mixing_eps_bases():
    empty=event(actual_eps=None,estimated_eps=None)
    complete=event(actual_eps=2,estimated_eps=1)
    result=ingest.unique_payload([empty,complete],{"ABC":1},"capture")
    assert result==ingest.unique_payload([complete,empty],{"ABC":1},"capture")
    assert result[0][0]["estimated_eps"]==1


def test_normalized_tickers_and_distinct_dates_use_database_conflict_key():
    rows=[event(ticker="BF.B"),event(ticker="BF-B"),event(ticker="BF-B",date="2026-10-09"),
          event(ticker="OUTSIDE"),event(ticker="BF-B",date=None)]
    payload,ignored,duplicates=ingest.unique_payload(rows,{"BF-B":1},"capture")
    assert len(payload)==2 and ignored==1 and duplicates==1
    assert {r["reported_date"] for r in payload}=={"2026-10-08","2026-10-09"}


def test_incremental_deduplicates_across_batches_before_any_database_write(monkeypatch):
    rows=[event(date=f"2026-01-{i%28+1:02}",ticker=f"S{i}") for i in range(260)]
    rows+=[event(ticker="S0",date="2026-01-01",updated="2026-10-10T00:00:00Z",actual_eps=3)]
    saved=[]
    class Query:
        def select(self,*args): return self
        def eq(self,*args): return self
        def order(self,*args,**kwargs): return self
        def execute(self): return type("Result",(),{"data":[{"id":i+1,"ticker":f"S{i}"} for i in range(260)]})()
        def upsert(self,payload,**kwargs):
            assert kwargs["on_conflict"]=="company_id,reported_date,source"
            keys=[(r["company_id"],r["reported_date"],r["source"]) for r in payload]
            assert len(keys)==len(set(keys))
            saved.extend(payload)
            return self
    class Db:
        def table(self,*args): return Query()
    class Provider:
        async def earnings(self,**kwargs): return rows
    monkeypatch.setattr(ingest,"get_supabase",Db)
    monkeypatch.setattr(ingest,"MassiveProvider",Provider)
    monkeypatch.setattr(ingest,"watermark",lambda *args:"2026-10-01")
    monkeypatch.setattr(ingest.sys,"argv",["ingest","--incremental"])
    asyncio.run(ingest.main())
    assert len(saved)==260
    assert next(r for r in saved if r["company_id"]==1)["reported_eps"]==3


def test_watermark_uses_successful_refresh_start_not_partial_batch_capture():
    calls=[]
    class Query:
        def select(self,*args): return self
        def eq(self,*args): calls.append(args);return self
        def order(self,*args,**kwargs): return self
        def limit(self,*args): return self
        def execute(self): return type("Result",(),{"data":[{"started_at":"2026-10-07T13:19:40+00:00"}]})()
    class Db:
        def table(self,name):
            assert name=="pipeline_runs"
            return Query()
    assert ingest.watermark(Db(),30)=="2026-10-06T07:19:40+00:00"
    assert ("pipeline","earnings_refresh") in calls
    assert ("status","success") in calls


def test_missing_history_backfill_requests_only_uncovered_share_class(monkeypatch):
    requested=[];saved=[]
    class Query:
        def select(self,*args): return self
        def eq(self,*args): return self
        def order(self,*args,**kwargs): return self
        def execute(self): return type("Result",(),{"data":[{"id":1,"ticker":"BF-B"},{"id":2,"ticker":"ABC"}]})()
        def upsert(self,payload,**kwargs): saved.extend(payload);return self
    class Db:
        def table(self,*args): return Query()
    class Provider:
        async def earnings(self,ticker):
            requested.append(ticker)
            return [event(ticker="BF/B",actual_eps=1)]
    monkeypatch.setattr(ingest,"get_supabase",Db)
    monkeypatch.setattr(ingest,"MassiveProvider",Provider)
    monkeypatch.setattr(ingest,"missing_earnings_companies",lambda db:[{"id":1,"ticker":"BF-B"}])
    monkeypatch.setattr(ingest.sys,"argv",["ingest","--backfill-missing"])
    asyncio.run(ingest.main())
    assert requested==["BF.B"]
    assert len(saved)==1 and saved[0]["company_id"]==1


def test_backfill_write_failure_cannot_be_reported_as_success(monkeypatch):
    import pytest
    class Query:
        def select(self,*args): return self
        def eq(self,*args): return self
        def order(self,*args,**kwargs): return self
        def execute(self): return type("Result",(),{"data":[{"id":1,"ticker":"ABC"}]})()
        def upsert(self,*args,**kwargs): raise RuntimeError("database write failed")
    class Db:
        def table(self,*args): return Query()
    class Provider:
        async def earnings(self,ticker): return [event(actual_eps=1)]
    monkeypatch.setattr(ingest,"get_supabase",Db)
    monkeypatch.setattr(ingest,"MassiveProvider",Provider)
    monkeypatch.setattr(ingest,"missing_earnings_companies",lambda db:[{"id":1,"ticker":"ABC"}])
    monkeypatch.setattr(ingest.sys,"argv",["ingest","--backfill-missing"])
    with pytest.raises(RuntimeError,match="Earnings collection failed for: ABC"):
        asyncio.run(ingest.main())
