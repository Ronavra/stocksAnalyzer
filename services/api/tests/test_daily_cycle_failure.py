import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db import client
from scripts import validate_daily_cycle


def test_daily_sync_precedes_prices_and_failure_preserves_missing_tickers(monkeypatch):
    script=Path(__file__).resolve().parents[1]/"scripts"/"run_daily_cycle.py"
    monkeypatch.syspath_prepend(str(script.parent))
    calls=[]
    updates=[]
    class Db:
        def rpc(self,name,params):
            assert name=="claim_daily_market_refresh"
            return SimpleNamespace(execute=lambda:SimpleNamespace(data={"run":True,"id":99}))
        def table(self,name):
            assert name=="pipeline_runs"
            return self
        def update(self,payload):
            updates.append(payload)
            return self
        def eq(self,*args): return self
        def execute(self): return None
    health={"ok":False,"expected_market_date":"2026-10-07","latest_price_date":"2026-10-07",
            "latest_feature_date":"2026-10-07","price_companies":503,"feature_companies":0,
            "universe_companies":504,"missing_prices":["WBD"],"missing_features":["WBD"]}
    monkeypatch.setattr(client,"get_supabase",lambda:Db())
    monkeypatch.setattr(validate_daily_cycle,"validate",lambda db:health)
    monkeypatch.setattr("subprocess.run",lambda command,**kwargs:calls.append(Path(command[1]).name))
    with pytest.raises(RuntimeError,match="503/504.*missing_prices=\\['WBD'\\]"):
        runpy.run_path(str(script),run_name="__main__")
    assert calls==["sync_sp500.py","ingest_prices.py"]
    assert updates[-1]["status"]=="error"
    assert updates[-1]["expected_market_date"]=="2026-10-07"
    assert updates[-1]["metadata"]["freshness"]["missing_prices"]==["WBD"]
