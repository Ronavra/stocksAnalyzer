from datetime import date, timedelta

import pytest

from app.research.weekly_backtest import historical_catalyst, replay, setup_at, summarize


def feature(day, future=.02):
    return {"feature_date": day, "close": 100, "drawdown_60d": -.10,
            "distance_to_support_60d": .05, "rebound_potential_60d": .10,
            "forward_return_5d": future, "forward_return_10d": future,
            "forward_return_20d": future}


def test_setup_purges_unmatured_labels_and_uses_live_score():
    days = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(66)]
    rows = [feature(day) for day in days]
    for r in rows[-5:]:
        r["forward_return_5d"] = -.50
    result = setup_at(rows, 65)
    assert result["sample_size"] == 61
    assert result["up"] == 1
    assert result["median"] == .02
    # 61 positive examples: shrinkage and evidence weights match scan_setups.py.
    shrunk = (61 + 10) / (61 + 20)
    expected = 100 * (.50 * min(1, (shrunk - .45) / .25) + .30 * .6 + .20 * .5) * (.65 + .35 * .61)
    assert result["score"] == pytest.approx(round(expected, 2))


def test_earnings_catalyst_must_precede_close_date_and_be_recent():
    events = [{"reported_date": x} for x in
              ("2024-01-01", "2024-01-10", "2024-02-02", "2024-02-05")]
    assert historical_catalyst(events, "2024-02-02")["reported_date"] == "2024-01-10"
    assert historical_catalyst(events, "2024-03-20") is None


def test_replay_selects_without_looking_at_future_returns():
    anchor = date(2024, 2, 2)
    days = [(anchor - timedelta(days=i)).isoformat() for i in range(60, -1, -1)]
    series = {cid: [feature(d) for d in days] for cid in range(1, 8)}
    series[7][-1]["forward_return_5d"] = .01  # SPY
    series[1][-1]["forward_return_5d"] = None
    weeks = replay(series, {}, 7, anchor.isoformat())
    assert len(weeks) == 1
    assert len(weeks[0]["setup_only"]) == 5
    # Missing outcome disqualifies the cohort from evaluation, not the stock
    # from the historical selection made at the anchor close.
    assert 1 in [p["company_id"] for p in weeks[0]["setup_only"]]
    assert summarize(weeks)["horizons"]["5"]["setup_only"] == {"cohorts": 0}
    assert summarize(weeks)["horizons"]["5"]["recent_earnings"] == {"cohorts": 0}
