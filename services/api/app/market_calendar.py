from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

NY=ZoneInfo("America/New_York")

def observed(d):
    if d.weekday()==5: return d-timedelta(days=1)
    if d.weekday()==6: return d+timedelta(days=1)
    return d

def nth_weekday(year,month,weekday,n):
    d=date(year,month,1)
    return d+timedelta(days=(weekday-d.weekday())%7+7*(n-1))

def last_weekday(year,month,weekday):
    d=date(year+1,1,1)-timedelta(days=1) if month==12 else date(year,month+1,1)-timedelta(days=1)
    return d-timedelta(days=(d.weekday()-weekday)%7)

def easter_sunday(year):
    a=year%19; b=year//100; c=year%100; d=b//4; e=b%4; f=(b+8)//25; g=(b-f+1)//3
    h=(19*a+b-d-g+15)%30; i=c//4; k=c%4; l=(32+2*e+2*i-h-k)%7
    m=(a+11*h+22*l)//451; month=(h+l-7*m+114)//31; day=(h+l-7*m+114)%31+1
    return date(year,month,day)

def full_day_holidays(year):
    holidays={
        observed(date(year,1,1)),
        nth_weekday(year,1,0,3),
        nth_weekday(year,2,0,3),
        easter_sunday(year)-timedelta(days=2),
        last_weekday(year,5,0),
        observed(date(year,6,19)),
        observed(date(year,7,4)),
        nth_weekday(year,9,0,1),
        nth_weekday(year,11,3,4),
        observed(date(year,12,25)),
    }
    # A New Year's Day observed on Dec 31 belongs to the following year's holiday.
    next_new_year=observed(date(year+1,1,1))
    if next_new_year.year==year: holidays.add(next_new_year)
    return holidays

def is_trading_day(d):
    return d.weekday()<5 and d not in full_day_holidays(d.year)

def latest_completed_session(now=None,data_ready_hour=17):
    now=now or datetime.now(NY)
    d=now.date()
    if now.hour < data_ready_hour:
        d-=timedelta(days=1)
    while not is_trading_day(d):
        d-=timedelta(days=1)
    return d
