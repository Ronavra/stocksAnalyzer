from datetime import date,timedelta,datetime,timezone
from copy import deepcopy
import random
import pytest
from app.research import twenty_day_model as model
from app.research.active_portfolio import CONFIG
from app.research.observations import close_cutoff,available
from app.research.macro_features import macro_asof


def test_delayed_twenty_session_labels_use_exact_prices_and_not_signal_close_returns():
    days=model.exchange_calendar('2026-07-01','2026-09-30');anchor=days[0]
    prices={1:{d:100+i for i,d in enumerate(days)},2:{d:200 for d in days}}
    prep={'spy_id':2,'price_history':prices,'latest_date':days[-1],
        'companies':{1:{'ticker':'ABC'},2:{'ticker':'SPY'}},'rows':[{'company_id':1,'feature_date':anchor}],
        'features':{(1,anchor):{k:1 for k in model.BASE}}}
    record=model.prepared_records(prep)['records'][0]
    assert record['actual_return']==pytest.approx(121/101-1)
    assert record['label_end_date']==days[21]
    del prices[1][days[21]]
    assert model.prepared_records(prep)['records'][0]['actual_return'] is None


def test_training_never_uses_current_or_future_exit_labels():
    rows=[{'label_end_date':d,'target_excess':.1} for d in ('2026-10-01','2026-10-02','2026-10-03')]
    assert model.training_before(rows,'2026-10-02')==rows[:1]


def test_research_stays_blocked_with_short_history_and_does_not_promote():
    report=model.validate({'records':[],'latest_date':'2026-10-22'})
    assert report['outcome']=='insufficient_history' and report['promotion_passed'] is False
    assert report['active_selection_changed'] is False


def test_macro_never_uses_todays_backfill_as_past_knowledge_and_vintages_wait_one_day():
    row={'series_id':'DGS10','observation_date':'2026-10-01','value':4,'units':'percent',
         'source':'fred_current_csv','observed_at':'2026-10-22T12:00:00Z','vintage_date':None}
    assert macro_asof([row],'2026-10-02')['macro_yield_10y'] is None
    vintage={**row,'source':'alfred_vintage','vintage_date':'2026-10-01'}
    assert macro_asof([vintage],'2026-10-01')['macro_yield_10y'] is None
    assert macro_asof([vintage],'2026-10-02')['macro_yield_10y']==4
    assert macro_asof([{**row,'value':float('nan')}],'2026-10-22')['macro_yield_10y'] is None


def test_early_close_blocks_observations_captured_after_actual_exchange_close():
    day='2026-11-27'
    assert close_cutoff(day).hour==13
    assert not available({'observed_at':day+'T14:00:00-05:00'},close_cutoff(day))


def test_funded_research_costs_are_independent_of_production_and_no_leverage():
    days=model.exchange_calendar('2026-07-01','2026-10-01');prices={};companies={}
    for cid in range(1,13):
        rng=random.Random(cid);value=100.;prices[cid]={};companies[cid]={'ticker':f'S{cid}','sector':f'Sector {cid%5}'}
        for day in days:
            value*=1+rng.uniform(-.005,.006);prices[cid][day]=value
    companies[12]['ticker']='SPY'
    prepared={'calendar':days,'prices':prices,'spy_id':12,'companies':companies}
    outputs={day:[{'company_id':i,'expected_return':.1,'expected_excess':.1,'downside_p10':-.02} for i in range(1,12)] for day in days[:30:5]}
    base=model.simulate(outputs,prepared);stress=model.simulate(outputs,prepared,cost=.005)
    assert len(base['state']['positions'])<=10 and base['state']['cash']>=0
    assert stress['state']['costs']>base['state']['costs']>0
    assert CONFIG['one_way_cost']==.001
    assert not base['issues']


def test_family_choice_is_frozen_before_the_final_audit(monkeypatch):
    dates=[(date(2020,1,3)+timedelta(days=7*i)).isoformat() for i in range(190)]
    records=[{'date':d,'label_end_date':(date.fromisoformat(d)+timedelta(days=29)).isoformat()} for d in dates]
    calls=[]
    def walk(rows,days,family):
        calls.append((min(days),family))
        if family not in ('price_context','earnings'):raise RuntimeError('insufficient family history')
        return {'phase':'holdout' if min(days)>=dates[152] else 'selection','family':family},[]
    monkeypatch.setattr(model,'simulate',lambda out,p,cost=.002:dict(out,cost=cost))
    def fake_metrics(sim,base=None):
        # Earnings wins selection and loses audit; no choosing a different winner after seeing the audit.
        score=.3 if sim['family']=='earnings' and sim['phase']=='selection' else .1
        return {'net_return':score,'complete':True,'weeks':30,'lower_bound_vs_spy':.01,'lower_bound_vs_base':-.01,
                'max_drawdown':-.1,'excess_vs_spy':-.01 if sim['phase']=='holdout' else .1}
    monkeypatch.setattr(model,'metrics',fake_metrics)
    report=model.validate({'records':records,'latest_date':'2025-01-01'},walker=walk)
    assert report['selected_family']=='earnings' and report['promotion_passed'] is False
    assert report['selection_last_exit']<report['holdout_start']
    assert report['statistical_gates_passed'] is False
    assert {f for d,f in calls if d==report['holdout_start']}=={'price_context','earnings'}
