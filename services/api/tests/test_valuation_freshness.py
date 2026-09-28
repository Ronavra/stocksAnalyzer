from datetime import date, timedelta

from scripts.build_daily_valuation import MAX_TTM_AGE_DAYS, recent_ttm


def test_only_recent_filing_period_can_generate_a_current_valuation():
    asof=date(2026,9,25)
    assert recent_ttm({"period_end":str(asof-timedelta(days=MAX_TTM_AGE_DAYS))},asof.isoformat())
    assert not recent_ttm({"period_end":str(asof-timedelta(days=MAX_TTM_AGE_DAYS+1))},asof.isoformat())
    assert not recent_ttm({"period_end":str(asof+timedelta(days=1))},asof.isoformat())
    assert not recent_ttm({"period_end":None},asof.isoformat())
