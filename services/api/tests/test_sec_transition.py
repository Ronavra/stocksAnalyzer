from datetime import date
from app.providers.sec_transition import transition_ttm,interval_total


def facts(value,begin,end,form='10-Q',filed='2026-08-10'):
    return {'start':begin,'end':end,'val':value,'form':form,'filed':filed,'accn':'source'}


def history(scale=1):
    return [facts(120*scale,'2024-08-01','2025-07-31','10-K'),
            facts(50*scale,'2024-08-01','2024-12-31','10-KT'),
            facts(60*scale,'2025-01-01','2025-06-30'),
            facts(55*scale,'2025-08-01','2025-12-31','10-KT'),
            facts(66*scale,'2026-01-01','2026-06-30')]


def test_transition_uses_exact_interval_identity_and_never_five_months_as_annual():
    data={'facts':{'us-gaap':{tag:{'units':{'USD':history(scale)}} for tag,scale in [('Revenues',1),('NetIncomeLoss',.1),('NetCashProvidedByUsedInOperatingActivities',.2),('PaymentsToAcquirePropertyPlantAndEquipment',.05)]}}}
    report={'period_end':'2026-06-30','filed_date':'2026-08-10'}
    quarter={'period_end':'2026-06-30','filed_date':'2026-08-10','revenue':33,'net_income':3.3,'eps_diluted':1.5,'cash':9,'total_debt':20}
    row=transition_ttm(data,report,quarter)
    assert row['revenue']==131 and abs(row['net_income']-13.1)<1e-9
    assert abs(row['free_cash_flow']-19.65)<1e-9 and row['cash']==9
    assert row['eps_diluted'] is None and len(row['supplemental']['ttm_interval_basis']['revenue']['components'])==5
    assert quarter['revenue']==33 and quarter['eps_diluted']==1.5


def test_missing_interval_or_future_filing_cannot_fill_transition_ttm():
    rows=history()
    assert interval_total(rows[:-1],date(2025,7,1),date(2026,7,1),'2026-08-10')==(None,None)
    rows[-1]['filed']='2026-08-11'
    assert interval_total(rows,date(2025,7,1),date(2026,7,1),'2026-08-10')==(None,None)


def test_same_day_conflicting_values_are_not_arbitrarily_chosen():
    rows=[facts(10,'2025-07-01','2026-06-30','10-K'),facts(20,'2025-07-01','2026-06-30','10-K')]
    assert interval_total(rows,date(2025,7,1),date(2026,7,1),'2026-08-10')==(None,None)


def test_inconsistent_overlapping_reported_periods_do_not_produce_ttm():
    rows=[facts(10,'2025-07-01','2026-06-30','10-K'),facts(6,'2025-07-01','2025-12-31'),facts(6,'2026-01-01','2026-06-30')]
    assert interval_total(rows,date(2025,7,1),date(2026,7,1),'2026-08-10')==(None,None)


def test_revenue_aliases_cannot_mix_incompatible_partial_series():
    rows=history()
    data={'facts':{'us-gaap':{'Revenues':{'units':{'USD':rows[:-1]}},'RevenueFromContractWithCustomerExcludingAssessedTax':{'units':{'USD':rows[-1:]}}}}}
    assert transition_ttm(data,{'period_end':'2026-06-30','filed_date':'2026-08-10'},{'period_end':'2026-06-30'}) is None
