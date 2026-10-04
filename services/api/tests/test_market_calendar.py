from datetime import date,datetime
from zoneinfo import ZoneInfo
from app.market_calendar import is_trading_day,latest_completed_session

def test_new_year_saturday_does_not_close_prior_year_end():
    assert is_trading_day(date(2021,12,31))
    assert is_trading_day(date(2027,12,31))
    assert not is_trading_day(date(2027,1,1))

def test_juneteenth_and_exceptional_nyse_closure():
    assert is_trading_day(date(2021,6,18))
    assert not is_trading_day(date(2022,6,20))
    assert not is_trading_day(date(2025,1,9))
    assert latest_completed_session(datetime(2025,1,9,18,tzinfo=ZoneInfo('America/New_York')))==date(2025,1,8)
