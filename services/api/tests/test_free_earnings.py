from datetime import datetime, date, timedelta, timezone
import math
import pytest
from app.providers.free_earnings import yahoo_payload, parse_alpha_calendar, event_day
from app.research.free_calendar import calendar_assessment
from app.research.earnings_catalysts import upcoming_earnings, recent_earnings

NOW='2026-10-21T12:00:00+00:00'


def test_yahoo_keeps_provider_pairs_and_missing_revenue_unknown():
    snapshot, rows = yahoo_payload(1,{'Earnings Date':[date(2026,10,28),date(2026,10,30)]},[
        {'Earnings Date':datetime(2026,10,20,20,tzinfo=timezone.utc),'Reported EPS':1.2,'EPS Estimate':1.0},
        {'Earnings Date':date(2026,10,28),'Reported EPS':math.nan,'EPS Estimate':1.4},
        {'Earnings Date':date(2026,10,22),'Reported EPS':2,'EPS Estimate':1}],NOW)
    assert snapshot['dates']==['2026-10-28','2026-10-30']
    assert snapshot['status']=='observed'
    assert len(rows)==1 and rows[0]['surprise_percent']==pytest.approx(20)
    assert rows[0]['actual_revenue'] is None and rows[0]['revenue_surprise_percent'] is None
    assert rows[0]['source']=='yahoo_finance' and rows[0]['captured_at']==NOW


def test_empty_or_past_calendar_is_unknown_and_not_a_clear_window():
    snapshot, rows = yahoo_payload(1,{'Earnings Date':[date(2026,10,20)]},[],NOW)
    assert snapshot['dates']==[] and snapshot['status']=='unknown'
    assert rows==[]
    assert calendar_assessment([snapshot],[1],'2026-10-20',NOW)[1]['calendar_status']=='unknown'


def test_zero_estimate_has_unknown_percentage_and_duplicate_report_is_one_row():
    record={'Earnings Date':date(2026,10,20),'Reported EPS':1,'EPS Estimate':0}
    _, rows = yahoo_payload(1,{},[record,record],NOW)
    assert len(rows)==1 and rows[0]['surprise_percent'] is None


def test_dates_are_converted_to_the_market_timezone():
    assert event_day(datetime(2026,10,21,0,30,tzinfo=timezone.utc))==date(2026,10,20)


def test_alpha_bulk_csv_and_auth_quota_notices():
    got=parse_alpha_calendar('symbol,reportDate,estimate\nBRK.B,2026-11-02,3.4\nBAD,unknown,\n')
    assert got=={'BRK-B':[date(2026,11,2)]}
    for body in ('{"Information":"25 requests exhausted"}', 'symbol,reportDate\n', '<html>Denied</html>'):
        with pytest.raises(RuntimeError):
            parse_alpha_calendar(body)


def test_stale_future_capture_and_missing_issuer_never_pass_calendar_gate():
    rows=[{'company_id':1,'source':'yahoo_finance','status':'observed','dates':['2026-11-15'],'observed_at':'2026-10-18T12:00:00Z'},
          {'company_id':2,'source':'alphavantage','status':'observed','dates':['2026-11-15'],'observed_at':'2026-10-22T12:00:00Z'}]
    got=calendar_assessment(rows,[1,2,3],'2026-10-20',NOW)
    assert all(x['calendar_status']=='unknown' for x in got.values())


def test_conflicting_fresh_sources_keep_the_earliest_risk_date():
    rows=[{'company_id':1,'source':'yahoo_finance','status':'observed','dates':['2026-11-15'],'observed_at':NOW},
          {'company_id':1,'source':'alphavantage','status':'observed','dates':['2026-10-23'],'observed_at':NOW}]
    got=calendar_assessment(rows,[1],'2026-10-20',NOW)[1]
    assert got['calendar_status']=='current' and got['reported_date']=='2026-10-23'
    assert 5 in got['within_execution_horizons']
    assert got['calendar_sources']==['alphavantage','yahoo_finance']


def test_a_distant_observed_report_is_current_without_near_term_exclusion():
    rows=[{'company_id':1,'source':'yahoo_finance','status':'observed','dates':['2027-01-15'],'observed_at':NOW}]
    got=calendar_assessment(rows,[1],'2026-10-20',NOW)[1]
    assert got['calendar_status']=='current'
    assert not got.get('within_execution_horizons')


def test_upcoming_loader_returns_an_explicit_unknown_for_every_missing_candidate():
    class Db:
        def rpc(self,name,params):
            assert name=='free_earnings_calendar' and set(params['p_company_ids'])=={1,2}
            return type('Result',(),{'execute':lambda self:type('Response',(),{'data':[]})()})()
    got=upcoming_earnings(Db(),[{'company_id':1},{'company_id':2}],'2026-10-20',NOW)
    assert got=={cid:{'calendar_status':'unknown','calendar_sources':[],'calendar_observed_at':None} for cid in (1,2)}


def test_recent_free_results_replace_same_day_vendor_pair_without_merging():
    from test_earnings_catalysts import FakeEarningsQuery
    rows=[{'company_id':1,'reported_date':'2026-10-19','source':'massive_benzinga','captured_at':'2026-10-19','surprise_percent':8,'revenue_surprise_percent':4},
          {'company_id':1,'reported_date':'2026-10-19','source':'yahoo_finance','captured_at':'2026-10-21','surprise_percent':10,'revenue_surprise_percent':None}]
    class Db:
        def table(self,name): return FakeEarningsQuery(rows)
    got=recent_earnings(Db(),[{'company_id':1,'price_date':'2026-10-20'}])[1]
    assert got['source']=='yahoo_finance' and got['surprise_percent']==10
    assert got['revenue_surprise_percent'] is None


def test_unknown_calendar_blocks_otherwise_eligible_live_candidate():
    from test_financial_ranking import inputs_and_candidates, NOW as RANK_NOW, ASOF
    from app.research.financial_ranking import rank_candidates
    inputs, rows=inputs_and_candidates()
    calendars={cid:{'calendar_status':'current'} for cid in range(1,11)}
    calendars[10]={'calendar_status':'unknown'}
    picks, summary=rank_candidates(rows,inputs,ASOF,now=RANK_NOW,upcoming=calendars)
    assert 10 not in [p['row']['company_id'] for p in picks]
    assert summary['rejected']['earnings_calendar_unknown']==1
    assert summary['weights']=={'financial':.45,'technical':.35,'analyst':.1,'earnings':.1}


def test_provider_surprise_keeps_precision_lost_in_displayed_eps_values():
    _, rows = yahoo_payload(1,{},[{'Earnings Date':date(2026,10,20),
        'Reported EPS':2.02,'EPS Estimate':1.89,'Surprise(%)':6.74}],NOW)
    assert rows[0]['surprise_percent']==6.74
