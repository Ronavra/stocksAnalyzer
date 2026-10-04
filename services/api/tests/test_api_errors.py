from fastapi.testclient import TestClient
from app.main import app

def unavailable():
    raise RuntimeError('sensitive internal detail')

def test_data_failure_is_explicit_and_redacted(monkeypatch):
    monkeypatch.setattr('app.routers.research.get_supabase',unavailable)
    response=TestClient(app,raise_server_exceptions=False).get('/api/v1/research/signals')
    assert response.status_code==503
    assert response.json()['code']=='DATA_UNAVAILABLE'
    assert 'sensitive' not in response.text

def test_readiness_distinguishes_database_outage_from_liveness(monkeypatch):
    monkeypatch.setattr('app.main.get_supabase',unavailable)
    client=TestClient(app,raise_server_exceptions=False)
    assert client.get('/health').status_code==200
    response=client.get('/ready')
    assert response.status_code==503
    assert response.json()['database']=='unavailable'
