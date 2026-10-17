"""Verify the real dashboard health endpoint with the hosted database."""
import json
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR));load_dotenv(API_DIR/".env")
from fastapi.testclient import TestClient
from app.main import app


def main():
    started=time.monotonic()
    response=TestClient(app,raise_server_exceptions=False).get('/api/v1/research/system-health')
    elapsed=time.monotonic()-started
    if response.status_code!=200:
        raise RuntimeError(f"Dashboard health returned HTTP {response.status_code}")
    data=response.json()
    if not data.get('latest_price_date') or not data.get('market_freshness'):
        raise RuntimeError('Dashboard health omitted market data')
    if elapsed>=25:
        raise RuntimeError('Dashboard health approaches the client 30-second timeout')
    report={key:data.get(key) for key in ('status','latest_price_date','latest_feature_date','expected_market_date','market_data_current','financial_ranking_policy')}
    report['elapsed_seconds']=round(elapsed,3)
    report['response_bytes']=len(response.content)
    (API_DIR/'dashboard_health_check.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


if __name__=="__main__":main()
