"""Recent, point-in-time earnings catalysts for close-based research signals."""

from datetime import date, timedelta, datetime, timezone
from app.market_calendar import is_trading_day


MAX_CATALYST_AGE_DAYS = 30


def upcoming_earnings(db, candidates, signal_date, observed_at=None):
    """Expected report dates are risk flags; they do not alter selection weights."""
    if not candidates:
        return {}
    observed_at = observed_at or datetime.now(timezone.utc).isoformat()
    day = date.fromisoformat(signal_date)
    sessions = []
    while len(sessions) < 20:
        day += timedelta(days=1)
        if is_trading_day(day):
            sessions.append(day.isoformat())
    events = (db.table("earnings_events")
              .select("company_id,reported_date,event_time,estimated_eps,estimated_revenue,source,captured_at")
              .in_("company_id", [r["company_id"] for r in candidates])
              .gt("reported_date", signal_date).lte("reported_date", sessions[-1])
              .lte("captured_at", observed_at).is_("reported_eps", "null")
              .order("reported_date").limit(1000).execute().data or [])
    result = {}
    for event in events:
        item = dict(event)
        item["date_status"] = "expected"
        item["within_horizons"] = [h for h in (5, 10, 20) if item["reported_date"] <= sessions[h-1]]
        result.setdefault(item["company_id"], item)
    return result


def recent_earnings(db, candidates):
    """Return the latest eligible report for each candidate's own price date.

    The provider's event time is not always reliable. Requiring the report to
    precede the price date avoids treating an after-close report as information
    known at that close. Reports older than 30 days are not new catalysts.
    """
    asof = {
        r["company_id"]: date.fromisoformat(str(r.get("price_date") or r.get("as_of_date")))
        for r in candidates
        if r.get("company_id") and (r.get("price_date") or r.get("as_of_date"))
    }
    if not asof:
        return {}

    first = min(asof.values()) - timedelta(days=MAX_CATALYST_AGE_DAYS)
    last = max(asof.values())
    events = []
    start = 0
    while True:
        page = (db.table("earnings_events")
                .select("company_id,reported_date,surprise_percent,revenue_surprise_percent,source")
                .in_("company_id", list(asof))
                .eq("source", "massive_benzinga")
                .gte("reported_date", first.isoformat())
                .lt("reported_date", last.isoformat())
                .order("reported_date", desc=True)
                .range(start, start + 999).execute().data or [])
        events.extend(page)
        if len(page) < 1000:
            break
        start += 1000

    latest = {}
    for event in events:
        cid = event["company_id"]
        reported = date.fromisoformat(event["reported_date"])
        if cid in asof and 0 < (asof[cid] - reported).days <= MAX_CATALYST_AGE_DAYS:
            latest.setdefault(cid, event)
    return latest


def catalyst_adjustment(event):
    event = event or {}
    values = []
    for key in ("surprise_percent", "revenue_surprise_percent"):
        try:
            if event.get(key) is not None:
                values.append(float(event[key]))
        except (TypeError, ValueError):
            continue
    return max(-8, min(8, sum(max(-20, min(20, x)) for x in values) / 5)) if values else 0
