"""Fresh observed dates gate live selection; empty/missing calendars stay unknown."""
from datetime import datetime, timedelta, timezone, date
from .earnings_catalysts import upcoming_from_events
from ..market_calendar import NY


def calendar_assessment(rows, company_ids, signal_date, observed_at=None):
    now = datetime.fromisoformat(observed_at.replace('Z','+00:00')) if observed_at else datetime.now(timezone.utc)
    grouped = {cid:[] for cid in company_ids}
    for row in rows:
        try:
            stamp = datetime.fromisoformat(row['observed_at'].replace('Z','+00:00'))
        except (KeyError, ValueError, TypeError):
            continue
        if row.get('company_id') not in grouped or not timedelta(0) <= now-stamp <= timedelta(hours=48):
            continue
        if row.get('status') != 'observed':
            continue
        for value in row.get('dates') or []:
            try:
                day = date.fromisoformat(value)
            except (ValueError, TypeError):
                continue
            # An already passed event does not establish a current calendar.
            if day >= max(date.fromisoformat(signal_date), now.astimezone(NY).date()):
                grouped[row['company_id']].append({**row, 'reported_date':value, 'date_status':'projected'})
    result = {}
    for cid, events in grouped.items():
        upcoming = upcoming_from_events(events, signal_date).get(cid, {})
        result[cid] = {**upcoming, 'calendar_status':'current' if events else 'unknown',
                       'calendar_sources':sorted({r['source'] for r in events}),
                       'calendar_observed_at':max((r['observed_at'] for r in events),default=None)}
    return result
