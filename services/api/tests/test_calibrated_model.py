from datetime import date, timedelta

import pytest

from app.research import calibrated_model as model


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
