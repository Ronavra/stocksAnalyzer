"""Regression coverage for transient calendar writes and pilot price integrity."""
from unittest.mock import MagicMock

import pytest
from postgrest.exceptions import APIError

from scripts.refresh_free_earnings import store_calendar_snapshot
from scripts.track_real_money_pilot import positive, EXPECTED, BENCHMARK


def _gateway_error():
    return APIError({"code": 502, "message": "Bad Gateway"})


def test_calendar_snapshot_retry_checks_ambiguous_write(monkeypatch):
    db = MagicMock()
    snapshot = {"company_id": 3, "source": "yahoo_finance", "observed_at": "2026-10-30T12:00:00Z"}
    db.table.return_value.insert.return_value.execute.side_effect = [_gateway_error(), None]
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    monkeypatch.setattr("scripts.refresh_free_earnings.time.sleep", lambda _: None)
    monkeypatch.setattr("random.random", lambda: 0)
    store_calendar_snapshot(db, snapshot)
    assert db.table.return_value.insert.return_value.execute.call_count == 2


def test_calendar_snapshot_ambiguous_commit_not_inserted_twice(monkeypatch):
    db = MagicMock()
    snapshot = {"company_id": 3, "source": "yahoo_finance", "observed_at": "2026-10-30T12:00:00Z"}
    db.table.return_value.insert.return_value.execute.side_effect = _gateway_error()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": 42}]
    monkeypatch.setattr("scripts.refresh_free_earnings.time.sleep", lambda _: None)
    store_calendar_snapshot(db, snapshot)
    assert db.table.return_value.insert.return_value.execute.call_count == 1


def test_permanent_calendar_database_error_is_not_masked():
    db = MagicMock()
    db.table.return_value.insert.return_value.execute.side_effect = APIError({"code": "23505", "message": "unique"})
    with pytest.raises(APIError):
        store_calendar_snapshot(db, {"company_id": 3, "source": "x", "observed_at": "2026-10-30T12:00:00Z"})


def test_pilot_requires_positive_quotes_and_spy():
    assert len(EXPECTED) == 5 and BENCHMARK not in EXPECTED
    assert positive(None) is None
    assert positive("NaN") is None
    assert positive(-10) is None
    assert positive("155.5") == 155.5
