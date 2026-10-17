from copy import deepcopy
from datetime import datetime,timezone
import pytest
from app.research.expectation_features import estimate_asof,revision,analyst_asof
from app.research.model_readiness import execution_status
from app.research.portfolio_risk import weights_for
from scripts.run_local_model_validation import due
from scripts.repair_financial_coverage import repair_targets
from scripts.ingest_sec_fundamentals import preserve_recovered_fields


def estimate(day,value=1,**kw):
    return {"captured_at":day+"T12:00:00Z","fiscal_period_end":"2026-12-31","period_type":"quarter",
            "source":"test","eps_consensus":value,"revenue_consensus":100*value,
            "eps_basis":"adjusted","eps_currency":"USD","revenue_currency":"USD",**kw}


def test_revisions_use_observed_same_fiscal_target_and_never_future_captures():
    rows=[estimate("2026-10-01",1),estimate("2026-10-08",1.1),estimate("2026-10-09",10),
          estimate("2026-10-01",50,fiscal_period_end="2027-03-31")]
    r=estimate_asof(rows,"2026-10-08")
    assert r["estimate_eps_revision_7d"]==pytest.approx(.1)
    assert r["estimate_revenue_revision_7d"]==pytest.approx(.1)
    assert r["estimate_eps_revision_30d"] is None


def test_revisions_do_not_mix_bases_currencies_or_relabel_old_snapshots():
    rows=[estimate("2026-10-01",-1),estimate("2026-10-08",-.5)]
    assert estimate_asof(rows,"2026-10-08")["estimate_eps_revision_7d"]==.5
    rows[1]["eps_basis"]="unknown";rows[1]["revenue_currency"]="EUR"
    r=estimate_asof(rows,"2026-10-08")
    assert r["estimate_eps_revision_7d"] is None and r["estimate_revenue_revision_7d"] is None
    assert revision(float('nan'),1) is None
    assert all(v is None for v in estimate_asof([estimate("2026-08-01")],"2026-10-08").values())


def test_future_analyst_capture_is_not_a_historical_feature():
    row={"observed_at":"2026-10-09T12:00:00Z","period_date":"2026-10-01","source":"test",
         "strong_buy":5,"buy":5,"hold":0,"sell":0,"strong_sell":0}
    assert all(v is None for v in analyst_asof([row],"2026-10-08").values())
    assert analyst_asof([row],"2026-10-09")["analyst_count"]==10


def risk_rows():
    return [{"company_id":i,"model_diagnostics":{"selection_context":{"sector":"Financials" if i<4 else "Technology",
            "volatility_20d":.01*i,"observed_at":"2026-10-11T12:00:00Z"}}} for i in range(1,6)]


def test_risk_caps_leave_cash_and_do_not_backfill_old_sector_classifications():
    rows=risk_rows();w,error=weights_for(rows,"equal_sector_cap",published_at="2026-10-11T13:00:00Z")
    assert error is None and sum(w[i] for i in (1,2,3))==pytest.approx(.4)
    assert sum(w.values())==pytest.approx(.8)
    inverse,error=weights_for(rows,"inverse_volatility_sector_cap")
    assert inverse[1]>inverse[2] and sum(inverse.values())<=1
    rows[0]["model_diagnostics"]={}
    assert weights_for(rows,"equal_sector_cap")[1]=="sector_not_frozen_at_publication"
    assert weights_for(risk_rows(),"equal_sector_cap",published_at="2026-10-10T00:00:00Z")[1]=="risk_snapshot_after_publication"


def test_expired_validation_is_not_shown_as_still_running_or_validated():
    now=datetime(2026,10,17,12,tzinfo=timezone.utc)
    old={"status":"running","started_at":"2026-10-16T15:00:00Z"}
    assert execution_status(old,now)["status"]=="interrupted" and old["status"]=="running"
    assert execution_status({**old,"started_at":"2026-10-17T11:00:00Z"},now)["status"]=="running"


def test_research_week_catches_up_after_saturday_and_handles_dst():
    now=datetime(2026,10,17,12,tzinfo=timezone.utc)
    assert due([],now)
    assert not due([{"status":"success","finished_at":"2026-10-17T11:30:00Z"}],now)
    assert due([{"status":"error","finished_at":"2026-10-17T11:30:00Z"}],now)
    assert due([{"status":"success","finished_at":"2026-10-10T12:00:00Z"}],now)


def test_field_repair_prioritizes_core_gaps_and_keeps_reported_values_bound_to_filing():
    rows=[{"ticker":"A","missing_fields":["total_debt"]},{"ticker":"B","missing_fields":["revenue","eps_diluted"]}]
    assert repair_targets({"companies":rows},1)[0]["ticker"]=="B"
    old={"company_id":1,"period_end":"2026-06-30","period_type":"ttm","filed_date":"2026-08-01",
         "accession_number":"original","source":"sec","free_cash_flow":10,
         "supplemental":{"filing_recovery":{"accessions":["original"]}}}
    current={**old,"free_cash_flow":None,"supplemental":{}}
    preserve_recovered_fields(current,old)
    assert current["free_cash_flow"]==10
    current={**old,"free_cash_flow":None,"accession_number":"amended"}
    preserve_recovered_fields(current,old)
    assert current["free_cash_flow"] is None
    current={**old,"free_cash_flow":12}
    preserve_recovered_fields(current,old)
    assert current["free_cash_flow"]==12


def test_current_quarter_estimate_is_available_after_period_end_before_the_report():
    rows=[estimate('2026-10-01',1,fiscal_period_end='2026-09-30',relative_period='0q'),
          estimate('2026-10-08',1.1,fiscal_period_end='2026-09-30',relative_period='0q')]
    assert estimate_asof(rows,'2026-10-08')['estimate_eps_revision_7d']==pytest.approx(.1)
