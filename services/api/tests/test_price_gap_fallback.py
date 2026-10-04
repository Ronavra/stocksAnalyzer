import pytest
from app.research.price_gap_fallback import corroborated_gap_bars, valid_bar

def bar(day, close=100, source="twelvedata"):
    return {"price_date":f"2026-08-{day:02d}", "close":close, "open":close,
            "high":close+1, "low":close-1, "volume":100, "source":source}

def test_fills_only_missing_market_session_without_replacing_primary():
    existing=[bar(7),bar(11)]
    fallback=[bar(7,100.01,"yahoo_finance"),bar(8),bar(10),bar(11)]
    result=corroborated_gap_bars(existing,fallback,["2026-08-07","2026-08-10","2026-08-11"])
    assert result == [fallback[2]]
    assert existing == [bar(7),bar(11)]

def test_rejects_wrong_adjustment_or_symbol():
    with pytest.raises(ValueError,match="disagrees"):
        corroborated_gap_bars([bar(7),bar(11)], [bar(7,50),bar(10),bar(11,50)], ["2026-08-10"])

@pytest.mark.parametrize("existing", [[bar(7)], [bar(11)], [bar(1),bar(20)]])
def test_requires_nearby_anchors_on_both_sides(existing):
    with pytest.raises(ValueError,match="both sides"):
        corroborated_gap_bars(existing,[*existing,bar(10)],["2026-08-10"])

@pytest.mark.parametrize("close", [float("nan"),float("inf"),0,-1,None])
def test_rejects_nonfinite_or_nonpositive_price(close):
    assert not valid_bar({**bar(10),"close":close})
    with pytest.raises(ValueError,match="Invalid"):
        corroborated_gap_bars([bar(7),bar(11)],[bar(7),{**bar(10),"close":close},bar(11)],["2026-08-10"])

def test_rejects_duplicate_sessions():
    with pytest.raises(ValueError,match="Duplicate"):
        corroborated_gap_bars([bar(7),bar(11)],[bar(7),bar(10),bar(10),bar(11)],["2026-08-10"])

@pytest.mark.parametrize("extra", [{"high":99},{"low":101},{"volume":-1},{"open":float("nan")}])
def test_rejects_invalid_ohlcv(extra):
    assert not valid_bar({**bar(10),**extra})
