from datetime import date, timedelta

import numpy as np
import pytest

from app.research import calibrated_model as model
from app.research.validation_gate import validated_horizons


def test_fundamental_asof_uses_latest_period_without_future_filings():
    snapshots={1:[
        {"filed_date":"2026-08-01","period_end":"2026-06-30","values":{"_ttm_eps":5}},
        {"filed_date":"2026-09-01","period_end":"2025-12-31","values":{"_ttm_eps":2}},
        {"filed_date":"2026-11-01","period_end":"2026-09-30","values":{"_ttm_eps":8}},
    ]}
    assert model.fundamental_asof(snapshots,1,"2026-10-02")["_ttm_eps"]==5
    assert model.fundamental_asof(snapshots,1,"2026-11-02")["_ttm_eps"]==8
    assert all(v is None for v in model.fundamental_asof(snapshots,1,"2026-07-01").values())


def test_recently_filed_old_period_is_not_a_fresh_financial_feature():
    snapshots={1:[{"filed_date":"2026-10-01","period_end":"2020-12-31","values":{"_ttm_eps":5}}]}
    assert all(v is None for v in model.fundamental_asof(snapshots,1,"2026-10-02").values())


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
    monkeypatch.setattr(model,"load_price_rows",lambda *args:pytest.fail("Prepared snapshot must avoid another multi-year download"))
    assert model._prepare(None) is prepared


def test_validation_gate_requires_two_recorded_horizons():
    run={
        "status":"success","model_version":model.MODEL_VERSION,"best_stage":"price",
        "results":{"price":{"horizons":{
            "5":{"evaluation_protocol":"chronological_calibration_selection_holdout_v4","selection_beats_baseline":True,"selection_calibrated_brier":0.23,"selection_baseline_brier":0.25,"beats_baseline":True,"oof_rows":1100,"calibrated_brier":0.23,"baseline_brier":0.25},
            "10":{"evaluation_protocol":"chronological_calibration_selection_holdout_v4","selection_beats_baseline":True,"selection_calibrated_brier":0.24,"selection_baseline_brier":0.25,"beats_baseline":True,"oof_rows":1100,"calibrated_brier":0.24,"baseline_brier":0.25},
            "20":{"evaluation_protocol":"chronological_calibration_selection_holdout_v4","selection_beats_baseline":True,"selection_calibrated_brier":0.24,"selection_baseline_brier":0.25,"beats_baseline":False,"oof_rows":1100,"calibrated_brier":0.26,"baseline_brier":0.25},
        }}},
    }
    assert validated_horizons(run)==(5,10)
    run["results"]["price"]["horizons"]["10"]["oof_rows"]=999
    assert validated_horizons(run)==()
    run["results"]["price"]["horizons"]["10"]["oof_rows"]=1100
    run["results"]["price"]["horizons"]["10"]["selection_calibrated_brier"]=0.26
    assert validated_horizons(run)==()
    run["results"]["price"]["horizons"]["10"]["selection_calibrated_brier"]=0.24
    run["results"]["price"]["horizons"]["10"]["evaluation_protocol"]="older_in_sample_protocol"
    assert validated_horizons(run)==()
    run["results"]["price"]["horizons"]["10"]["evaluation_protocol"]="chronological_calibration_selection_holdout_v4"
    run["status"]="error"
    assert validated_horizons(run)==()


def test_final_holdout_rejects_reversed_signal(monkeypatch):
    """A pattern learned and selected earlier must fail when it reverses later."""
    days=[(date(2024,1,1)+timedelta(days=i)).isoformat() for i in range(300)]
    rows=[]; features={}
    for i,day in enumerate(days):
        for cid in range(100):
            signal=1 if cid%2 else -1
            outcome=signal if i<246 else -signal
            rows.append({"company_id":cid,"feature_date":day,"forward_return_5d":float(outcome)})
            features[(cid,day)]={"return_1d":float(signal)}

    monkeypatch.setattr(model,"HORIZONS",(5,))
    monkeypatch.setattr(model,"_prepare",lambda db,years:{
        "rows":rows,"all_dates":days,"latest_date":days[-1],"features":features,
        "fundamental_companies":0,"earnings_companies":0,"guidance_companies":0,
    })

    class FixedClassifier:
        def fit(self,x,y):
            return self

        def predict_proba(self,x):
            p=np.where(x[:,0]>0,.8,.2)
            return np.column_stack((1-p,p))

    class ZeroRegressor:
        def fit(self,x,y):
            return self

        def predict(self,x):
            return np.zeros(len(x))

    monkeypatch.setattr(model,"_classifier",FixedClassifier)
    monkeypatch.setattr(model,"_regressor",ZeroRegressor)
    models,_=model.fit_models(None,min_rows=1000,groups=("price",))
    diagnostics=models[5].diagnostics
    assert diagnostics["selection_beats_baseline"]
    assert not diagnostics["calibration_beats_baseline"]
    assert diagnostics["selection_rows"]>=1000
    assert diagnostics["oof_rows"]>=1000
    assert models[5].expected_return({"return_1d":1}) is None
