from copy import deepcopy
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app.main import app
from app.routers import research


class SnapshotDb:
    def __init__(self,snapshot):
        self.snapshot=snapshot
        self.calls=[]
    def rpc(self,name,params):
        self.calls.append((name,params))
        assert name=='research_system_health_snapshot'
        return SimpleNamespace(execute=lambda:SimpleNamespace(data=deepcopy(self.snapshot)))
    def table(self,*args):
        raise AssertionError('System health must use one snapshot, not serial table reads')


def sample(fresh=True):
    return {'runs':{'daily_market_research':{'status':'success','started_at':'2026-10-16T05:00:00Z',
        'finished_at':'2026-10-16T06:00:00Z','metadata':{'price_session_quality':{'incorrect_labels':0}}}},
        'latest_price_date':'2026-10-16','latest_feature_date':'2026-10-16',
        'freshness':{'ok':fresh,'missing_prices':[],'missing_features':[]},
        'audit':{'universe':503,'fundamentals':501,'earnings':490}}


def test_health_is_one_request_and_optional_reports_are_not_required(monkeypatch):
    db=SnapshotDb(sample())
    monkeypatch.setattr(research,'get_supabase',lambda:db)
    monkeypatch.setattr(research,'schedule_status',lambda *args:{'overdue':False})
    response=TestClient(app).get('/api/v1/research/system-health')
    assert response.status_code==200
    data=response.json()
    assert data['latest_price_date']=='2026-10-16'
    assert data['market_data_current'] and data['status']=='success'
    assert data['model_validation'] is None and data['research_enrichment'] is None
    assert data['coverage']['universe']==503
    assert data['financial_ranking_policy']['weights']=={'financial':.45,'technical':.35,'analyst':.1,'earnings':.1}
    assert len(db.calls)==1
    assert db.calls[0][1]['p_ranker_version']==research.RANKER_VERSION


def test_old_success_does_not_make_incomplete_market_data_healthy(monkeypatch):
    db=SnapshotDb(sample(False))
    monkeypatch.setattr(research,'get_supabase',lambda:db)
    monkeypatch.setattr(research,'schedule_status',lambda *args:{'overdue':False})
    data=TestClient(app).get('/api/v1/research/system-health').json()
    assert data['status']=='stale' and not data['market_data_current']
    assert data['latest_price_date']=='2026-10-16'


def test_snapshot_failure_stays_an_explicit_redacted_error(monkeypatch):
    monkeypatch.setattr(research,'get_supabase',lambda:SnapshotDb(None))
    response=TestClient(app,raise_server_exceptions=False).get('/api/v1/research/system-health')
    assert response.status_code==503
    assert response.json()['code']=='DATA_UNAVAILABLE'
