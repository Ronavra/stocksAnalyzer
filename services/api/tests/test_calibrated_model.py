from datetime import date, timedelta

import pytest

from app.research import calibrated_model as model
from app.research.validation_gate import validated_horizons


def test_prepare_sector_valuation_uses_sampled_dates(monkeypatch):
    dates=[(date(2020,12,21)+timedelta(days=i)).isoformat() for i in range(7)]
    rows=[
        {"company_id":cid,"feature_date":day,"close":close}
        for day in dates for cid,close in ((1,10),(2,20))
    ]
    monkeypatch.setattr(model,"load_price_rows",lambda db,years:(rows,dates[-1]))
    monkeypatch.setattr(model,"_companies",lambda db:{
        1:{"ticker":"AAA","sector":"Tech"},
        2:{"ticker":"BBB","sector":"Tech"},
    })
    monkeypatch.setattr(model,"load_ttm_fundamentals",lambda db:{})
    monkeypatch.setattr(model,"load_earnings_features",lambda *args:{})
    monkeypatch.setattr(model,"load_guidance_features",lambda db:{})
    monkeypatch.setattr(model,"fundamental_asof",lambda *args:{
        "_ttm_eps":10,"_ttm_fcf":10,"_shares_outstanding":10,
    })
    monkeypatch.setattr(model,"_PREP_CACHE",{})

    prepared=model._prepare(None)

    assert {r["feature_date"] for r in prepared["rows"]}=={dates[0],dates[5],dates[6]}
    assert len(prepared["features"])==6
    for day in (dates[0],dates[5],dates[6]):
        assert prepared["features"][(1,day)]["valuation_pe_vs_sector"]==pytest.approx(-1/3)
        assert prepared["features"][(2,day)]["valuation_fcf_yield_vs_sector"]==pytest.approx(-0.025)


def test_validation_gate_requires_two_recorded_horizons():
    run={
        "status":"success","model_version":model.MODEL_VERSION,"best_stage":"price",
        "results":{"price":{"horizons":{
            "5":{"beats_baseline":True,"oof_rows":1100,"calibrated_brier":0.23,"baseline_brier":0.25},
            "10":{"beats_baseline":True,"oof_rows":1100,"calibrated_brier":0.24,"baseline_brier":0.25},
            "20":{"beats_baseline":False,"oof_rows":1100,"calibrated_brier":0.26,"baseline_brier":0.25},
        }}},
    }
    assert validated_horizons(run)==(5,10)
    run["results"]["price"]["horizons"]["10"]["oof_rows"]=999
    assert validated_horizons(run)==()
    run["results"]["price"]["horizons"]["10"]["oof_rows"]=1100
    run["status"]="error"
    assert validated_horizons(run)==()
