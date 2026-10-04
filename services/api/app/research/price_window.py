from bisect import bisect_left


def canonical_prices(rows):
    """One bar per company/session; Twelve Data takes precedence over FMP."""
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
    if first is None or last is None or float(first) <= 0 or float(last) <= 0:
        return None
    return float(last) / float(first) - 1


def recent_distinct_prices(fetch_page, limit=100, page_size=100):
    """Return the newest trading dates, regardless of duplicate provider rows."""
    by_date = {}
    offset = 0
    while len(by_date) < limit:
        page = fetch_page(offset, page_size)
        for row in page:
            # The query orders preferred providers first within each date.
            by_date.setdefault(row["price_date"], row)
        offset += len(page)
        if len(page) < page_size:
            break
    return [by_date[date] for date in sorted(by_date)[-limit:]]
