"""Shared freshness checks for daily completion and API status."""
from math import isfinite

def _fresh_ids(db, table, date_column, expected):
    ids = set()
    for offset in range(0, 1000000, 1000):
        query = (db.table(table).select("company_id,close").eq(date_column,expected)
                 .order("company_id"))
        if table == "price_history":
            query = query.order("source")
        rows = query.range(offset,offset+999).execute().data or []
        for row in rows:
            try:
                close = float(row["close"])
                if isfinite(close) and close > 0:
                    ids.add(row["company_id"])
            except (KeyError,TypeError,ValueError,OverflowError):
                pass
        if len(rows) < 1000:
            return ids
    raise RuntimeError("Freshness pagination limit exceeded")

def market_freshness(db, expected):
    ds = expected.isoformat() if hasattr(expected,"isoformat") else expected
    price_ids = _fresh_ids(db,"price_history","price_date",ds)
    feature_ids = _fresh_ids(db,"price_features","feature_date",ds)
    universe = (db.table("companies").select("id,ticker")
                .or_("is_sp500.eq.true,scoring_profile.eq.benchmark").execute().data or [])
    missing_prices = [x["ticker"] for x in universe if x["id"] not in price_ids]
    missing_features = [x["ticker"] for x in universe if x["id"] not in feature_ids]
    current_ids = {x["id"] for x in universe}
    pc = len(price_ids & current_ids); fc = len(feature_ids & current_ids)
    ok = len(universe)>=500 and not missing_prices and not missing_features
    error = None if ok else (
        f"Freshness validation failed: expected {ds}; current_universe={len(universe)}; "
        f"prices={pc}, features={fc}; missing_prices={missing_prices[:20]}; "
        f"missing_features={missing_features[:20]}")
    return {"ok":ok,"expected_market_date":ds,
            "latest_price_date":ds if pc else None,"latest_feature_date":ds if fc else None,
            "price_companies":pc,"feature_companies":fc,"universe_companies":len(universe),
            "missing_prices":missing_prices,"missing_features":missing_features,
            "error_message":error}
