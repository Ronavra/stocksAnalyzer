"""Display closes from recommendation day, independently of execution outcomes."""

from math import isfinite

HORIZONS = (5, 10, 20)
PAGE_SIZE = 1000


def positive_price(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) and value > 0 else None


def price_timelines(signals, prices, market_dates):
    """Use exact market sessions; never substitute another day's stock close."""
    by_company = {}
    for row in prices:
        by_company.setdefault(row["company_id"], {})[row["price_date"]] = row
    calendar = sorted(set(market_dates))
    result = []
    for signal in signals:
        row = dict(signal)
        date = row["signal_date"]
        history = by_company.get(row["company_id"], {})
        diagnostics = row.get("model_diagnostics") or {}
        recommendation = positive_price(diagnostics.get("selection_close"))
        if recommendation is None and diagnostics.get("entry_policy") != "next_session_close":
            recommendation = positive_price(row.get("entry_price"))
        if recommendation is None:
            recommendation = positive_price(history.get(date, {}).get("close"))
        row["recommendation_price"] = recommendation
        row["recommendation_price_date"] = date
        latest_date = max(history, default=None)
        current = positive_price(history[latest_date].get("close")) if latest_date else None
        row["current_price"] = current
        row["current_price_date"] = latest_date
        row["change_since_recommendation"] = current / recommendation - 1 if current and recommendation else None
        entry = positive_price(row.get("entry_price"))
        row["return_since_signal"] = current / entry - 1 if current and entry else None
        sessions = [day for day in calendar if day > date]
        row["trading_days_elapsed"] = len(sessions) if calendar else None
        windows = {}
        for horizon in HORIZONS:
            target = sessions[horizon - 1] if len(sessions) >= horizon else None
            price = positive_price(history.get(target, {}).get("close")) if target else None
            status = "complete" if price else "missing" if target else "pending" if calendar else "calendar_unavailable"
            windows[str(horizon)] = {"price": price, "date": target, "status": status}
        row["price_windows"] = windows
        result.append(row)
    return result


def load_price_timelines(db, signals):
    if not signals:
        return []
    first_date = min(row["signal_date"] for row in signals)
    benchmark = db.table("companies").select("id").eq("ticker", "SPY").limit(1).execute().data or []
    spy_id = benchmark[0]["id"] if benchmark else None
    ids = sorted({row["company_id"] for row in signals} | ({spy_id} if spy_id is not None else set()))
    prices = []
    # Explicit inclusive ranges avoid Supabase's default 1,000-row truncation.
    start = 0
    while True:
        page = (db.table("price_history").select("company_id,price_date,close")
                .in_("company_id", ids).gte("price_date", first_date)
                .order("price_date").order("company_id")
                .range(start, start + PAGE_SIZE - 1).execute().data or [])
        prices.extend(page)
        if len(page) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    calendar = [row["price_date"] for row in prices if row["company_id"] == spy_id]
    return price_timelines(signals, prices, calendar)
