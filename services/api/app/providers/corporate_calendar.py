"""Projected ex-dividend dates from the same free Yahoo earnings response."""
from datetime import date,datetime,timedelta
from app.market_calendar import NY
from .free_earnings import event_day
from app.research.evidence import evidence_event


def projected_dividends(company_id,calendar,observed_at,ticker):
    value=calendar.get('Ex-Dividend Date') if isinstance(calendar,dict) else None
    if isinstance(value,(list,tuple)):value=value[0] if len(value)==1 else None
    when=event_day(value)
    today=datetime.fromisoformat(observed_at.replace('Z','+00:00')).astimezone(NY).date()
    if not when or not today<=when<=today+timedelta(days=400):return []
    when=when.isoformat()
    payment=event_day(calendar.get('Dividend Date'))
    payload={'ex_date':when,'amount':None,'currency':None,'date_status':'projected',
             'payment_date':payment.isoformat() if payment else None,'scope':'observed_upcoming_dividend_only'}
    return [evidence_event(company_id,'dividend','yahoo_calendar',when,
        f'https://finance.yahoo.com/quote/{ticker}/calendar/',payload,observed_at,when)]
