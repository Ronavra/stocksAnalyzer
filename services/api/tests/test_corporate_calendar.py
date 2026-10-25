from datetime import datetime,date,timezone
from app.providers.corporate_calendar import projected_dividends


def test_free_dividend_calendar_uses_ex_date_without_inventing_amount_or_publication():
    rows=projected_dividends(1,{'Ex-Dividend Date':date(2026,11,2),'Dividend Date':date(2026,11,12)},'2026-10-22T13:00:00Z','ABC')
    assert len(rows)==1 and rows[0]['event_date']=='2026-11-02'
    assert rows[0]['payload']['amount'] is None and rows[0]['published_at'] is None
    assert rows[0]['payload']['payment_date']=='2026-11-12'
    assert rows[0]['observed_at']=='2026-10-22T13:00:00Z'
    assert projected_dividends(1,{'Dividend Date':date(2026,11,12)},'2026-10-22T13:00:00Z','ABC')==[]
    assert projected_dividends(1,{'Ex-Dividend Date':date(2026,10,21)},'2026-10-22T13:00:00Z','ABC')==[]
