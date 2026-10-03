from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.research import financial_ranking as finance

NOW=datetime(2026,10,3,12,tzinfo=timezone.utc)
ASOF="2026-10-02"


def inputs_and_candidates(count=10,sector="Industrials"):
    companies={}; metrics={}; entries=[]; candidates=[]
    for cid in range(1,count+1):
        companies[cid]={"id":cid,"ticker":str(cid),"sector":sector}
        prior={"period_end":"2025-06-30","filed_date":"2025-08-01","revenue":100,"net_income":10,
               "eps_diluted":1,"operating_income":15,"free_cash_flow":10,"cash":5,"total_debt":20,"shares_outstanding":10}
        cur={"period_end":"2026-06-30","filed_date":"2026-08-01","revenue":100+cid*10,
             "net_income":10+cid*3,"eps_diluted":1+cid*.2,"operating_income":15+cid*4,
             "free_cash_flow":10+cid*4,"cash":5,"total_debt":100-cid*5,"shares_outstanding":10}
        metrics[cid]=[{"company_id":cid,**cur},{"company_id":cid,**prior}]
        entries.append({"company_id":cid,"status":"current","ttm_period":cur["period_end"],"ttm_filed_date":cur["filed_date"],
                        "latest_report":{"period_end":cur["period_end"],"filed_date":cur["filed_date"]}})
        candidates.append({"company_id":cid,"ticker":str(cid),"current_price":10,"opportunity_score":60,"setup_sample_size":100})
    audit={"scope":"full_universe","finished_at":"2026-10-03T11:00:00Z","companies":entries,"summary":{"universe_checked":count}}
    return {"companies":companies,"metrics":metrics,"audit":audit},candidates


def test_stronger_financials_outweigh_a_better_technical_score():
    inputs,rows=inputs_and_candidates()
    rows[-1]["opportunity_score"]=60
    rows[5]["opportunity_score"]=100
    picks,summary=finance.rank_candidates(rows,inputs,ASOF,now=NOW)
    assert picks[0]["row"]["company_id"]==10
    assert summary["weights"]=={"financial":.45,"technical":.35,"analyst":.10,"earnings":.10}
    assert picks[0]["score"]==round(sum(picks[0]["contributions"].values()),4)
    assert not summary["validated_forecast"]


def test_stale_ttm_and_unverified_filing_are_never_technical_fallbacks():
    inputs,rows=inputs_and_candidates()
    inputs["audit"]["companies"][-1]["status"]="ttm_behind_latest_filing"
    rows[-1]["opportunity_score"]=100
    picks,summary=finance.rank_candidates(rows,inputs,ASOF,now=NOW)
    assert 10 not in [p["row"]["company_id"] for p in picks]
    assert summary["rejected"]["filing_not_verified"]==1
    old=deepcopy(inputs["metrics"][1][0]); old["period_end"]="2025-12-31"
    assert finance.financial_snapshot([old],ASOF,inputs["audit"]["companies"][0])[1]=="old_ttm_period"


def test_recent_capture_cannot_make_an_old_audit_or_future_filing_eligible():
    inputs,rows=inputs_and_candidates()
    inputs["audit"]["finished_at"]="2026-09-30T11:00:00Z"
    with pytest.raises(RuntimeError,match="older than"):
        finance.rank_candidates(rows,inputs,ASOF,now=NOW)
    inputs["audit"]["finished_at"]="2026-10-03T11:00:00Z"
    inputs["audit"]["companies"][-1]["latest_report"]["filed_date"]="2026-10-05"
    scored,rejected=finance.financial_scores(rows,inputs,ASOF,now=NOW)
    assert 10 not in scored and rejected[10]=="ttm_does_not_match_verified_filing"


def test_missing_factors_keep_their_weights_and_reduce_score():
    inputs,rows=inputs_and_candidates()
    full,_=finance.financial_scores(rows,inputs,ASOF,now=NOW)
    inputs["metrics"][10][0]["total_debt"]=None
    partial,_=finance.financial_scores(rows,inputs,ASOF,now=NOW)
    assert partial[10]["coverage"]==.9
    assert partial[10]["score"]<full[10]["score"]
    factor=partial[10]["factors"]["net_debt_to_fcf"]
    assert factor["value"] is None and factor["score"] is None and factor["contribution"]==0
    inputs["metrics"][10][0]["shares_outstanding"]=None
    scored,rejected=finance.financial_scores(rows,inputs,ASOF,now=NOW)
    assert 10 not in scored and rejected[10]=="insufficient_financial_factor_coverage"


def test_negative_eps_is_not_treated_as_a_cheap_multiple():
    inputs,rows=inputs_and_candidates()
    snapshot,_=finance.financial_snapshot(inputs["metrics"][1],ASOF,inputs["audit"]["companies"][0])
    snapshot["latest"]["eps_diluted"]=-2
    assert finance.factors(snapshot,10)["earnings_yield"]==-.2


def test_financial_sector_does_not_require_industrial_cashflow_or_debt():
    inputs,rows=inputs_and_candidates(sector="Financials")
    for history in inputs["metrics"].values():
        for row in history:
            row["free_cash_flow"]=row["operating_income"]=row["cash"]=row["total_debt"]=None
    scored,_=finance.financial_scores(rows,inputs,ASOF,now=NOW)
    assert len(scored)==10 and scored[10]["coverage"]==1
    assert scored[10]["profile"]=="financial"
    assert "fcf_yield" not in scored[10]["factors"]


def test_small_peer_group_does_not_get_artificially_high_percentiles():
    inputs,rows=inputs_and_candidates(count=4)
    scored,rejected=finance.financial_scores(rows,inputs,ASOF,now=NOW)
    assert scored=={} and set(rejected.values())=={"insufficient_sector_peer_coverage"}


def test_unknown_earnings_is_neutral_and_records_missingness():
    inputs,rows=inputs_and_candidates()
    picks,_=finance.rank_candidates(rows,inputs,ASOF,now=NOW,top=1)
    assert len(picks)==1 and picks[0]["earnings_score"]==50
    assert not picks[0]["earnings_available"]


def test_historical_replay_uses_filing_dates_without_reusing_live_audit():
    inputs,rows=inputs_and_candidates()
    inputs["audit"]={}
    inputs["metrics"][10][0]["filed_date"]="2026-10-05"
    scored,rejected=finance.financial_scores(rows,inputs,ASOF,live=False)
    assert 10 not in scored and rejected[10]=="old_ttm_period"
    assert scored[9]["freshness_mode"]=="historical_filing_date_proxy"


def test_analyst_component_changes_order_and_keeps_neutral_weight_when_missing():
    inputs,rows=inputs_and_candidates()
    inputs["analyst_snapshots"]={9:[{"source":"yahoo_finance","observed_at":"2026-10-03T11:00:00Z",
        "period_date":"2026-10-01","strong_buy":100,"buy":0,"hold":0,"sell":0,"strong_sell":0}]}
    picks,summary=finance.rank_candidates(rows,inputs,ASOF,now=NOW)
    assert picks[0]["row"]["company_id"]==9
    assert picks[0]["analyst"]["available"]
    assert picks[0]["contributions"]["analyst"]==.1*picks[0]["analyst"]["score"]
    missing=next(p for p in picks if p["row"]["company_id"]==10)
    assert missing["contributions"]["analyst"]==5
    assert missing["contributions"]["financial"]==.45*missing["financial"]["score"]
    assert sum(summary["weights"].values())==1
