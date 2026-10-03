from copy import deepcopy
from datetime import date, timedelta

import pytest

from app.research.signal_prices import load_price_timelines, price_timelines


def signal(**overrides):
    return {"company_id": 1, "signal_date": "2026-09-04", "entry_price": 100,
            "horizon_days": 5, **overrides}


def prices(days, company_id=1):
    return [{"company_id": company_id, "price_date": day, "close": 101 + i}
            for i, day in enumerate(days)]


def test_windows_count_market_sessions_after_recommendation_not_calendar_days():
    # Labor Day and both weekends are absent from the market calendar.
    days = ["2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14"]
    row = price_timelines([signal()], prices(days), days)[0]
    assert row["price_windows"]["5"] == {"price": 105, "date": "2026-09-14", "status": "complete"}
    assert row["price_windows"]["10"]["status"] == "pending"
    assert row["trading_days_elapsed"] == 5
    assert row["current_price_date"] == "2026-09-14"
    assert row["change_since_recommendation"] == pytest.approx(.05)


def test_selection_close_and_display_windows_are_independent_of_execution_entry():
    days = ["2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15"]
    frozen = signal(entry_price=101, exit_price=106, exit_date=days[5],
                    actual_return=.0475, model_diagnostics={"entry_policy": "next_session_close", "selection_close": 100})
    before = deepcopy(frozen)
    row = price_timelines([frozen], prices(days), days)[0]
    assert row["recommendation_price"] == 100
    assert row["price_windows"]["5"]["price"] == 105
    assert row["price_windows"]["5"]["date"] != row["exit_date"]
    assert row["return_since_signal"] == pytest.approx(106 / 101 - 1)
    assert row["change_since_recommendation"] == pytest.approx(.06)
    assert frozen == before
    assert row["actual_return"] == frozen["actual_return"]


def test_new_selection_price_is_visible_before_next_session_entry_exists():
    row = price_timelines([signal(entry_price=None, model_diagnostics={"entry_policy": "next_session_close", "selection_close": "99.5"})],
                          prices(["2026-09-04"]), ["2026-09-04"])[0]
    assert row["recommendation_price"] == 99.5
    assert row["price_windows"]["5"]["status"] == "pending"
    assert row["return_since_signal"] is None


def test_missing_exact_window_price_is_not_replaced_with_next_or_latest_close():
    days = ["2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15"]
    history = [row for row in prices(days) if row["price_date"] != days[4]]
    row = price_timelines([signal()], history, days)[0]
    assert row["price_windows"]["5"] == {"price": None, "date": days[4], "status": "missing"}
    assert row["current_price"] == 106
    assert row["current_price_date"] == days[5]


def test_no_benchmark_calendar_is_unavailable_rather_than_claiming_window_pending():
    row = price_timelines([signal()], prices(["2026-09-08"]), [])[0]
    assert row["price_windows"]["5"]["status"] == "calendar_unavailable"
    assert row["trading_days_elapsed"] is None


@pytest.mark.parametrize("invalid", [None, 0, -1, "bad", float("nan"), float("inf")])
def test_invalid_prices_do_not_render_as_real_closes(invalid):
    days = ["2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14"]
    history = prices(days)
    history[-1]["close"] = invalid
    row = price_timelines([signal(entry_price=invalid)], history, days)[0]
    assert row["recommendation_price"] is None
    assert row["current_price"] is None
    assert row["current_price_date"] == days[-1]
    assert row["price_windows"]["5"]["status"] == "missing"
    assert row["change_since_recommendation"] is None


def test_delayed_entry_is_never_used_as_fallback_recommendation_price():
    frozen = signal(entry_price=150, model_diagnostics={"entry_policy": "next_session_close"})
    history = [{"company_id": 1, "price_date": "2026-09-04", "close": 100}]
    row = price_timelines([frozen], history, ["2026-09-04"])[0]
    assert row["recommendation_price"] == 100
    assert price_timelines([frozen], [], ["2026-09-04"])[0]["recommendation_price"] is None


def test_all_windows_and_each_cohort_have_their_own_dates():
    days = [(date(2026, 9, 4) + timedelta(days=i)).isoformat() for i in range(35)
            if (date(2026, 9, 4) + timedelta(days=i)).weekday() < 5]
    first, second = price_timelines([signal(), signal(signal_date=days[5])], prices(days), days)
    for horizon in (5, 10, 20):
        assert first["price_windows"][str(horizon)]["date"] == days[horizon]
        assert first["price_windows"][str(horizon)]["price"] == 101 + horizon
    assert second["price_windows"]["5"]["date"] == days[10]
    assert second["price_windows"]["20"]["status"] == "pending"


def test_paginated_loader_does_not_drop_latest_closes_after_first_thousand_rows():
    days = [(date(2026, 9, 4) + timedelta(days=i)).isoformat() for i in range(502)]
    history = sorted(prices(days) + prices(days, 2), key=lambda row: (row["price_date"], row["company_id"]))
    requested_ranges = []

    class Query:
        def __init__(self, table): self.name = table
        def select(self, *_): return self
        def eq(self, key, value):
            assert (key, value) == ("ticker", "SPY")
            return self
        def limit(self, *_): return self
        def in_(self, key, value):
            assert key == "company_id" and value == [1, 2]
            return self
        def gte(self, key, value):
            assert (key, value) == ("price_date", "2026-09-04")
            return self
        def order(self, *_): return self
        def range(self, start, end):
            requested_ranges.append((start, end))
            self.page = history[start:end + 1]
            return self
        def execute(self):
            return type("Response", (), {"data": [{"id": 2}] if self.name == "companies" else self.page})()

    class Db:
        def table(self, name): return Query(name)

    row = load_price_timelines(Db(), [signal()])[0]
    assert requested_ranges == [(0, 999), (1000, 1999)]
    assert row["current_price_date"] == days[-1]
    assert row["current_price"] == 602
    assert row["price_windows"]["20"]["date"] == days[20]


def test_empty_selection_needs_no_database_reads():
    assert load_price_timelines(None, []) == []
