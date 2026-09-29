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
