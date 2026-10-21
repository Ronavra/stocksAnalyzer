from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from scripts import refresh_free_earnings as collector


class Db:
    def __init__(self):
        self.snapshots=[]; self.events=[]; self.updates=[]; self.claim=True; self.break_writes=False
    def rpc(self,name,*args):
        data={'run':self.claim,'id':1} if name=='claim_free_earnings_refresh' else self.snapshots
        return SimpleNamespace(execute=lambda:SimpleNamespace(data=data))
    def table(self,name):
        db=self
        class Query:
            def select(self,*a): return self
            def eq(self,*a): return self
            def order(self,*a): return self
            def insert(self,rows):
                if db.break_writes and name=='earnings_calendar_snapshots': raise RuntimeError('database unavailable')
                if name=='earnings_calendar_snapshots': db.snapshots.extend(rows if isinstance(rows,list) else [rows])
                return self
            def upsert(self,rows,**kw): db.events.extend(rows); return self
            def update(self,row): db.updates.append(row); return self
            def execute(self):
                return SimpleNamespace(data=[{'id':1,'ticker':'AAA'},{'id':2,'ticker':'BBB'}] if name=='companies' else [])
        return Query()


@pytest.fixture
def setup(monkeypatch,tmp_path):
    monkeypatch.delenv('ALPHA_VANTAGE_API_KEY',raising=False)
    monkeypatch.setattr(collector,'API_DIR',tmp_path)


def test_no_api_key_collects_public_calendars_and_reports_partial_coverage(setup):
    future=(datetime.now(timezone.utc)+timedelta(days=10)).date()
    class Provider:
        def fetch(self,ticker): return ({'Earnings Date':[future]} if ticker=='AAA' else {}),[]
    db=Db(); report=collector.refresh(db,Provider(),delay=0)
    assert report['current_calendars']==1 and report['unknown_tickers']==['BBB']
    assert report['coverage_status']=='partial' and report['alpha_calendar']=='not_configured'
    assert not report['paid_endpoints_called']
    assert db.updates[-1]['status']=='success'


def test_all_calendars_unknown_blocks_refresh_instead_of_reporting_complete(setup):
    class Provider:
        def fetch(self,ticker): return {},[]
    db=Db()
    with pytest.raises(RuntimeError,match='No fresh earnings calendars'):
        collector.refresh(db,Provider(),delay=0)
    assert db.updates[-1]['status']=='error'


def test_database_failure_is_not_reclassified_as_provider_failure(setup):
    class Provider:
        def fetch(self,ticker): return {},[]
    db=Db(); db.break_writes=True
    with pytest.raises(RuntimeError,match='database unavailable'):
        collector.refresh(db,Provider(),delay=0)
    assert db.updates[-1]['status']=='error' and not db.updates[-1]['metadata']['errors']


def test_running_lease_does_not_create_a_false_success(setup):
    db=Db(); db.claim=False
    with pytest.raises(RuntimeError,match='already running'):
        collector.refresh(db,delay=0)
    assert not db.updates and not db.snapshots
