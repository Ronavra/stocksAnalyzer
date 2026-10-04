"""Strictly corroborate split-adjusted fallback bars before filling real holes."""
from datetime import date, timedelta
from math import isfinite
from app.research.price_window import canonical_prices

def valid_bar(row):
    try:
        close = float(row["close"])
        if not isfinite(close) or close <= 0:
            return False
        values = {}
        for key in ("open", "high", "low"):
            if row.get(key) is not None:
                values[key] = float(row[key])
                if not isfinite(values[key]) or values[key] <= 0:
                    return False
        if "high" in values and values["high"] < max(close, values.get("open", close)):
            return False
        if "low" in values and values["low"] > min(close, values.get("open", close)):
            return False
        if row.get("volume") is not None:
            volume = float(row["volume"])
            if not isfinite(volume) or volume < 0:
                return False
        date.fromisoformat(row["price_date"])
        return True
    except (KeyError, TypeError, ValueError, OverflowError):
        return False

def corroborated_gap_bars(existing, fallback, market_dates, tolerance=0.001):
    """Only absent SPY sessions, with matching closes on both sides within a week."""
    saved = {r["price_date"]: r for r in canonical_prices(existing)}
    proposed = {}
    for row in fallback:
        if not valid_bar(row):
            raise ValueError("Invalid fallback OHLCV bar")
        day = row["price_date"]
        if day in proposed:
            raise ValueError("Duplicate fallback session")
        proposed[day] = row
    overlap = sorted(set(saved) & set(proposed))
    for day in overlap:
        reference = saved[day]
        if not valid_bar(reference):
            raise ValueError("Invalid canonical reference bar")
        if abs(float(proposed[day]["close"]) / float(reference["close"]) - 1) > tolerance:
            raise ValueError("Fallback close disagrees with canonical source")
    accepted = []
    for day in sorted((set(market_dates) & set(proposed)) - set(saved)):
        target = date.fromisoformat(day)
        before = [d for d in overlap if target - timedelta(days=7) <= date.fromisoformat(d) < target]
        after = [d for d in overlap if target < date.fromisoformat(d) <= target + timedelta(days=7)]
        if not before or not after:
            raise ValueError("Gap lacks corroborating closes on both sides")
        accepted.append(proposed[day])
    return accepted
