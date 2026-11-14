from datetime import datetime
from scripts.run_local_model_validation import due


def at(value):
    return datetime.fromisoformat(value.replace("Z","+00:00"))


def test_saturday_validation_waits_until_after_friday_market_data_refresh():
    assert not due([], at("2026-11-14T13:00:00Z"))  # 15:00 Israel
    assert due([], at("2026-11-14T20:05:00Z"))  # 22:05 Israel


def test_successful_saturday_validation_is_not_repeated():
    previous=[{"status":"success","finished_at":"2026-11-14T20:01:00Z"}]
    assert not due(previous,at("2026-11-14T20:05:00Z"))
    assert not due(previous,at("2026-11-15T08:00:00Z"))
