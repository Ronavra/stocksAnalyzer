import pytest

from app.research.signal_execution import execution_update


def signal(delayed=True):
    return {"signal_date": "2026-09-25", "horizon_days": 5, "entry_price": None if delayed else 100,
            "model_diagnostics": {"entry_policy": "next_session_close", "round_trip_cost": .002} if delayed else {}}


def prices():
    return [{"price_date": day, "close": close} for day, close in
            zip(("2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05"),
                (110, 111, 112, 113, 114, 121))]


def test_new_signal_waits_for_entry_and_five_full_sessions():
    assert execution_update(signal(), []) == ({}, None)
    update, entry_date = execution_update(signal(), prices()[:1])
    assert entry_date is None
    assert update["entry_price"] == 110
    assert update["model_diagnostics"]["execution_entry_date"] == "2026-09-28"
    assert "actual_return" not in execution_update(signal(), prices()[:5])[0]
    update, entry_date = execution_update(signal(), prices())
    assert entry_date == "2026-09-28"
    assert update["exit_date"] == "2026-10-05"
    assert update["actual_return"] == pytest.approx(.098)
    assert update["model_diagnostics"]["gross_return"] == pytest.approx(.1)


def test_old_signals_keep_original_close_to_close_policy():
    update, entry_date = execution_update(signal(False), prices())
    assert entry_date == "2026-09-25"
    assert update["exit_date"] == "2026-10-02"
    assert update["actual_return"] == pytest.approx(.14)
    assert "entry_price" not in update
    assert "model_diagnostics" not in update


def test_missing_company_session_cannot_shift_entry_or_exit():
    calendar = [p["price_date"] for p in prices()]
    assert execution_update(signal(), prices()[1:], calendar) == ({}, None)
    update, entry_date = execution_update(signal(), prices()[:-1], calendar)
    assert entry_date is None
    assert "actual_return" not in update
