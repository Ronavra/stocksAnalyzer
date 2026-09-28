from datetime import date

from scripts import validate_daily_cycle as daily


class Query:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *args):
        return self

    def eq(self, field, value):
        self.rows = [r for r in self.rows if r.get(field) == value]
        return self

    def or_(self, *args):
        return self

    def execute(self):
        return type("Response", (), {"data": self.rows})()


class Db:
    def __init__(self, fresh_ids):
        self.universe = [{"id": i, "ticker": f"T{i}"} for i in range(1, 504)]
        # A removed stock still has a fresh bar but is not in the universe.
        self.fresh = [{"company_id": i, "price_date": "2026-09-28", "feature_date": "2026-09-28"}
                      for i in [*fresh_ids, 999]]

    def table(self, name):
        return Query(self.universe if name == "companies" else self.fresh.copy())


def test_stale_former_member_cannot_mask_missing_active_ticker(monkeypatch):
    monkeypatch.setattr(daily, "latest_expected_market_date", lambda: date(2026, 9, 28))
    result = daily.validate(Db(range(1, 503)))
    assert result["price_companies"] == 502
    assert result["feature_companies"] == 502
    assert result["missing_prices"] == ["T503"]
    assert result["missing_features"] == ["T503"]
    assert not result["ok"]


def test_all_current_members_fresh(monkeypatch):
    monkeypatch.setattr(daily, "latest_expected_market_date", lambda: date(2026, 9, 28))
    result = daily.validate(Db(range(1, 504)))
    assert result["ok"]
    assert result["price_companies"] == 503
    assert result["feature_companies"] == 503
