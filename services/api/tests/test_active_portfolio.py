from datetime import datetime, timezone, date, timedelta
import random
import pytest
from app.research.active_portfolio import advance, initial_state, sessions_after, pair_correlation
from app.market_calendar import is_trading_day
NOW=datetime(2026,10,21,12,tzinfo=timezone.utc)
ASOF='2026-10-20'


def candidates(n=15):
    return [dict(company_id=i,ticker=f'S{i}',score=90-i,sector=f'Sector {i%5}') for i in range(1,n+1)]


def prices(n=16):
    rows=[]
    for cid in range(1,n+1):
        rng=random.Random(cid); value=100.; day=date(2026,5,1)
        while day<=date(2026,12,31):
            if is_trading_day(day):
                value*=1+rng.uniform(-.01,.01)
                rows.append(dict(company_id=cid,price_date=day.isoformat(),close=value))
            day+=timedelta(days=1)
    return rows


def held(cid=1,score=60,sector='Sector 1',shares=100,review='2026-11-18'):
    return dict(company_id=cid,ticker=f'S{cid}',sector=sector,shares=shares,entry_price=100.,entry_date='2026-10-01',review_due=review,score=score,entry_score=score)


def test_ten_unique_funded_entries_never_at_a_past_close():
    s=advance(None,candidates(),prices(),ASOF,NOW)
    assert s['positions']==[] and len(s['orders'])==10
    assert len({o['company_id'] for o in s['orders']})==10
    assert {o['execute_on'] for o in s['orders']}=={'2026-10-22'}
    assert sum(o['budget'] for o in s['orders'])<=s['cash']
    assert s['validated'] is False


def test_fills_costs_and_rerun_deduplication():
    s=advance(None,candidates(),prices(),ASOF,NOW)
    now=datetime(2026,10,23,12,tzinfo=timezone.utc)
    filled=advance(s,candidates(),prices(),'2026-10-22',now)
    assert len(filled['positions'])==10 and filled['cash']>=0 and filled['costs']>0
    assert filled['equity']+filled['costs']==pytest.approx(100000.)
    again=advance(filled,candidates(),prices(),'2026-10-22',now)
    assert len(again['positions'])==10 and again['costs']==filled['costs'] and not again['orders']


def test_sector_cap_and_cash_instead_of_forced_picks():
    rows=candidates(); [c.update(sector='Technology') for c in rows]
    s=advance(None,rows,prices(),ASOF,NOW)
    assert sum(o['budget'] for o in s['orders'])<=30000.0001 and len(s['orders'])==3


def test_correlated_or_missing_history_blocks_new_entry():
    p=prices(2); first={r['price_date']:r['close'] for r in p if r['company_id']==1}
    for r in p:
        if r['company_id']==2: r['close']=first[r['price_date']]
    assert len(advance(None,candidates(2),p,ASOF,NOW)['orders'])==1
    assert len(advance(None,candidates(2),[r for r in p if r['company_id']==1],ASOF,NOW)['orders'])==1
    assert pair_correlation({'2026-10-20':100},{'2026-10-20':100},ASOF) is None


def test_unknown_data_does_not_trigger_sale():
    s=initial_state();s['positions']=[held()];s['cash']=90000
    out=advance(s,[],prices(),ASOF,NOW,ranking_error='SEC audit stale')
    assert not out['orders'] and len(out['positions'])==1
    assert any('calendar unknown' in a for a in out['alerts']) and any('paused' in a for a in out['alerts'])
    assert out['actions'][0]['action']=='review'


def test_earnings_risk_between_weekly_reviews():
    s=initial_state();s['positions']=[held()];s['cash']=90000;s['last_review_week']='2026-10-19'
    out=advance(s,[],prices(),ASOF,NOW,{1:{'calendar_status':'current','reported_date':'2026-10-22'}})
    assert out['orders'][0]['reason']=='earnings_approaching' and out['orders'][0]['execute_on']=='2026-10-22'
    assert any('precede' in a for a in out['alerts'])


def test_review_renewal_or_confirmed_score_exit():
    s=initial_state();s['positions']=[held(review='2026-10-20')];s['cash']=90000
    out=advance(s,candidates(1),prices(),ASOF,NOW,{1:{'calendar_status':'current'}})
    assert out['positions'][0]['review_due']>ASOF and not out['orders']
    out=advance(s,[],prices(),ASOF,NOW,{1:{'calendar_status':'current'}},{'1':'financial_score_below_minimum'})
    assert out['orders'][0]['side']=='sell'


def test_missing_execution_close_is_unresolved_not_shifted():
    s=advance(None,candidates(1),prices(),ASOF,NOW)
    p=[r for r in prices() if not (r['company_id']==1 and r['price_date']=='2026-10-22')]
    out=advance(s,candidates(),p,'2026-10-23',datetime(2026,10,26,12,tzinfo=timezone.utc))
    assert out['positions']==[] and len(out['orders'])==1 and any('unresolved' in a for a in out['alerts'])


def test_two_replacements_maximum_and_score_margin():
    s=initial_state();s['positions']=[held(i,sector=f'Sector {i%5}',shares=90) for i in range(1,11)];s['cash']=10000
    pool=[dict(company_id=i,ticker=f'S{i}',sector=f'Sector {i%5}',score=60 if i<=10 else 80) for i in range(1,16)]
    out=advance(s,pool,prices(),ASOF,NOW)
    assert len([o for o in out['orders'] if o['side']=='sell'])==2
    assert len([o for o in out['orders'] if o['side']=='buy'])==2
    pool=[dict(c,score=64) if c['company_id']>10 else c for c in pool]
    assert not advance(s,pool,prices(),ASOF,NOW)['orders']


def test_calendar_future_and_duplicate_positions():
    assert sessions_after('2026-11-25')=='2026-11-27' and sessions_after('2026-12-24')=='2026-12-28'
    with pytest.raises(ValueError,match='unfinished'): advance(None,[],[],'2026-10-21',NOW)
    s=initial_state();s['positions']=[held(),held()]
    with pytest.raises(ValueError,match='duplicate'): advance(s,[],prices(),ASOF,NOW)


def test_forward_experiments_cap_ten_and_schedule_exact_horizon_without_renewing():
    for h in (5,10,20):
        s=advance(None,candidates(),prices(),ASOF,NOW,fixed_horizon=h)
        buys=[o for o in s['orders'] if o['side']=='buy'];sells=[o for o in s['orders'] if o['side']=='sell']
        assert len(buys)==10 and len(sells)==10
        assert all(o['execute_on']==sessions_after('2026-10-22',h) for o in sells)
        # An outage through both entry and exit still fills chronological exact closes.
        target=sessions_after('2026-10-22',h)
        now=datetime.fromisoformat(target+'T23:00:00+00:00')
        out=advance(s,[],prices(),target,now,ranking_error='unavailable',fixed_horizon=h)
        assert out['positions']==[] and not out['orders']
        assert out['completed_trades']==10 and out['costs']>s['costs']


def test_early_risk_sale_replaces_future_experiment_exit():
    s=advance(None,candidates(1),prices(),ASOF,NOW,fixed_horizon=20)
    out=advance(s,[],prices(),'2026-10-22',datetime(2026,10,23,12,tzinfo=timezone.utc),
                {1:{'calendar_status':'current','reported_date':'2026-10-26'}},fixed_horizon=20)
    sales=[o for o in out['orders'] if o['side']=='sell']
    assert len(sales)==1 and sales[0]['reason']=='earnings_approaching'


def test_unresolved_buy_preserves_its_expiry_until_both_exact_prices_arrive():
    s=advance(None,candidates(1),prices(),ASOF,NOW,fixed_horizon=5)
    exit_day=sessions_after('2026-10-22',5)
    p=[r for r in prices() if not (r['company_id']==1 and r['price_date']=='2026-10-22')]
    now=datetime.fromisoformat(exit_day+'T23:00:00+00:00')
    missing=advance(s,[],p,exit_day,now,ranking_error='unavailable',fixed_horizon=5)
    assert len(missing['orders'])==2
    fixed=advance(missing,[],prices(),exit_day,now,ranking_error='unavailable',fixed_horizon=5)
    assert not fixed['orders'] and not fixed['positions'] and fixed['completed_trades']==1
