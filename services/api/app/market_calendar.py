from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

NY=ZoneInfo("America/New_York")
FULL_DAY_HOLIDAYS_2026={
    date(2026,1,1),date(2026,1,19),date(2026,2,16),date(2026,4,3),
    date(2026,5,25),date(2026,6,19),date(2026,7,3),date(2026,9,7),
    date(2026,11,26),date(2026,12,25),
}

def is_trading_day(d):
    return d.weekday()<5 and d not in FULL_DAY_HOLIDAYS_2026

def latest_completed_session(now=None, data_ready_hour=17):
    now=now or datetime.now(NY)
    d=now.date()
    if now.hour < data_ready_hour:
        d-=timedelta(days=1)
    while not is_trading_day(d):
        d-=timedelta(days=1)
    return d
