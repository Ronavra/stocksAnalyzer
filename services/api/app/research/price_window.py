from bisect import bisect_left
from math import isfinite


def canonical_prices(rows):
    """One bar per company/session; Twelve Data takes precedence over FMP and Yahoo fallback."""
    preferred = sorted(rows, key=lambda r: (r.get("source") != "twelvedata", r.get("source") or ""))
    by_date = {}
    for row in preferred:
        by_date.setdefault((row.get("company_id"), row["price_date"]), row)
    return sorted(by_date.values(), key=lambda r: (r["price_date"], r.get("company_id") or 0))


def session_return(prices, calendar, signal_date, horizon):
    """Missing exact-session closes stay missing, rather than shift the label."""
    index = bisect_left(calendar, signal_date)
    if index == len(calendar) or calendar[index] != signal_date:
        return None
    target = index + horizon
    if target < 0 or target >= len(calendar):
        return None
    first = (prices.get(signal_date) or {}).get("close")
    last = (prices.get(calendar[target]) or {}).get("close")
    if first is None or last is None or not isfinite(float(first)) or not isfinite(float(last)) or float(first) <= 0 or float(last) <= 0:
        return None
    return float(last) / float(first) - 1


def recent_distinct_prices(fetch_page, limit=100, page_size=100):
    """Newest sessions, with provider priority independent of row order."""
    rows = []
    offset = 0
    while True:
        page = fetch_page(offset, page_size)
        rows.extend(page)
        distinct = {r["price_date"] for r in rows}
        if len(page) < page_size:
            break
        if len(distinct) >= limit:
            cutoff = sorted(distinct)[-limit]
            # Read through cutoff date, including all providers across page boundaries.
            if page[-1]["price_date"] < cutoff:
                break
        offset += len(page)
    return canonical_prices(rows)[-limit:]
