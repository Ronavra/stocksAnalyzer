"""Public earnings observations. Unknown calendars never mean no event."""
import csv
import io
from datetime import date, datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo
import httpx

NY = ZoneInfo('America/New_York')


def number(value):
    try:
        value = float(value)
        return value if isfinite(value) else None
    except (TypeError, ValueError):
        return None


def event_day(value):
    if hasattr(value, 'to_pydatetime'):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.astimezone(NY).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def calendar_row(company_id, source, dates, observed_at):
    today = datetime.fromisoformat(observed_at.replace('Z', '+00:00')).astimezone(NY).date()
    valid = sorted({d.isoformat() for value in dates if (d := event_day(value)) is not None
                    and today <= d <= today + timedelta(days=400)})
    return {'company_id':company_id, 'source':source, 'observed_at':observed_at,
            'status':'observed' if valid else 'unknown', 'dates':valid,
            'source_url':'https://www.alphavantage.co/documentation/#earnings-calendar' if source == 'alphavantage'
                         else 'https://finance.yahoo.com/'}


def yahoo_payload(company_id, calendar, records, observed_at):
    today = datetime.fromisoformat(observed_at.replace('Z', '+00:00')).astimezone(NY).date()
    dates = list((calendar or {}).get('Earnings Date') or [])
    rows = {}
    for item in records:
        day = event_day(item.get('Earnings Date'))
        if day is None:
            continue
        actual, estimate = number(item.get('Reported EPS')), number(item.get('EPS Estimate'))
        if day >= today and actual is None:
            dates.append(day)
        if day > today or day < today-timedelta(days=120) or actual is None:
            continue
        delta = actual-estimate if estimate is not None else None
        rows[day.isoformat()] = {'company_id':company_id, 'reported_date':day.isoformat(),
                     'reported_eps':actual, 'estimated_eps':estimate, 'surprise':delta,
                     'surprise_percent':delta/abs(estimate)*100 if delta is not None and estimate != 0 else None,
                     'actual_revenue':None, 'estimated_revenue':None, 'revenue_surprise':None,
                     'revenue_surprise_percent':None, 'source':'yahoo_finance',
                     'source_record_id':day.isoformat(), 'captured_at':observed_at}
    # Never infer revenue surprise by mixing an old consensus with SEC actuals.
    return calendar_row(company_id, 'yahoo_finance', dates, observed_at), list(rows.values())


class YahooEarningsProvider:
    def fetch(self, ticker):
        import yfinance as yf
        company = yf.Ticker(ticker.replace('.', '-'))
        failed = 0
        try:
            calendar = company.get_calendar()
        except Exception:
            calendar = {}; failed += 1
        try:
            frame = company.get_earnings_dates(limit=12)
            records = [] if frame is None or frame.empty else frame.reset_index().to_dict('records')
        except Exception:
            records = []; failed += 1
        if failed == 2:
            raise RuntimeError('Yahoo calendar and earnings results unavailable')
        return calendar, records


class AlphaCalendarProvider:
    def __init__(self, api_key):
        self.api_key = api_key

    def fetch(self):
        # This bulk endpoint is one request, not one request per company.
        with httpx.Client(timeout=45) as client:
            response = client.get('https://www.alphavantage.co/query', params={
                'function':'EARNINGS_CALENDAR', 'horizon':'3month', 'apikey':self.api_key})
        if response.is_error:
            raise RuntimeError(f'Alpha calendar HTTP {response.status_code}')
        return parse_alpha_calendar(response.text)


def parse_alpha_calendar(text):
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not {'symbol','reportDate'}.issubset(reader.fieldnames):
        # Provider sometimes returns a JSON quota/auth notice with HTTP 200.
        raise RuntimeError('Alpha calendar unavailable or daily quota exhausted')
    grouped = {}
    for row in reader:
        ticker = (row.get('symbol') or '').upper().replace('.', '-')
        day = event_day(row.get('reportDate'))
        if ticker and day:
            grouped.setdefault(ticker, []).append(day)
    if not grouped:
        raise RuntimeError('Alpha calendar is empty; no completeness claim made')
    return grouped
