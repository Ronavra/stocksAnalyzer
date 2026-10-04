from app.research.prospective_metrics import prospective_metrics
import pytest

def cohort(version='old', date='2026-09-25', picks=2):
    return {'model_version':version,'signal_date':date,'horizons':[5,10,20],'expected_picks':picks}

def prediction(value, version='old', date='2026-09-25'):
    return {'model_version':version,'signal_date':date,'horizon_days':5,'evaluated_at':'2026-10-05',
            'actual_return':value,'excess_return':value-.02}

def test_partial_group_not_counted_and_versions_do_not_mix():
    rows=[prediction(.1),prediction(-.04),prediction(.9,'new')]
    result=prospective_metrics([cohort(),cohort('new')],rows,[])['by_policy']
    old=result['old']['by_horizon']['5']
    assert old['evaluated_cohorts']==1
    assert old['mean_net_return']==pytest.approx(.03)
    assert old['mean_excess_return']==pytest.approx(.01)
    assert result['new']['by_horizon']['5']['evaluated_cohorts']==0

def test_no_pick_week_matures_using_next_session_benchmark_and_duplicate_dates():
    days=['2026-09-28','2026-09-29','2026-09-30','2026-10-01','2026-10-02','2026-10-05']
    market=[{'price_date':d,'close':100+i,'source':'twelvedata'} for i,d in enumerate(days)]
    market += [{'price_date':days[0],'close':999,'source':'fmp'}]
    result=prospective_metrics([cohort(picks=0)],[],market)['by_policy']['old']['by_horizon']['5']
    assert result['cash_cohorts']==1
    assert result['mean_net_return']==0
    assert result['mean_excess_return']==pytest.approx(-.05)
    pending=prospective_metrics([cohort(picks=0)],[],market[:-2])['by_policy']['old']['by_horizon']['5']
    assert pending['evaluated_cohorts']==0
