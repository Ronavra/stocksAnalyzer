import runpy
from datetime import date, timedelta
from pathlib import Path

from app.db import client


class Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.company_id = None
        self.desc = False
        self.count = None
        self.window = None
        self.payload = None

    def select(self, *args):
        return self

    def eq(self, field, value):
        self.company_id = value
        return self

    def order(self, field, desc=False):
        if field in ("price_date", "feature_date"):
            self.desc = desc
        return self

    def limit(self, count):
        self.count = count
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def upsert(self, payload, **kwargs):
        self.payload = payload
        return self

    def execute(self):
        if self.payload is not None:
            self.db.saved.extend(self.payload)
            return type("Result", (), {"data": self.payload})()
        if self.table == "companies":
            rows = self.db.companies
        elif self.table == "price_history":
            rows = self.db.prices[self.company_id]
        else:
            rows = self.db.existing.get(self.company_id, [])
        rows = sorted(rows, key=lambda r: r.get("price_date", r.get("feature_date", "")), reverse=self.desc)
        if self.window is not None:
            start, end = self.window
            rows = rows[start:end + 1]
        return type("Result", (), {"data": rows[:self.count] if self.count else rows})()


class Db:
    def __init__(self):
        self.companies = [{"id": 1, "ticker": "SPY"},
                          {"id": 2, "ticker": "NEW"},
                          {"id": 3, "ticker": "OLD"}]
        days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(70)]
        self.prices = {cid: [{"price_date": day, "open": 100 + i, "high": 102 + i,
                               "low": 99 + i, "close": 101 + i, "volume": 1000}
                              for i, day in enumerate(days)] for cid in (1, 2, 3)}
        self.existing = {1: [{"feature_date": days[-2]}],
                         3: [{"feature_date": days[-2]}]}
        self.saved = []

    def table(self, name):
        return Query(self, name)


def test_new_constituent_gets_full_price_feature_history(monkeypatch):
    db = Db()
    monkeypatch.setattr(client, "get_supabase", lambda: db)
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_daily_price_features.py"
    runpy.run_path(str(script), run_name="__main__")
    fresh = [r for r in db.saved if r["company_id"] == 2]
    existing = [r for r in db.saved if r["company_id"] == 3]
    assert len(fresh) == 70
    assert len(existing) == 21
    assert fresh[25]["market_momentum_20d"] is not None
    assert fresh[10]["forward_return_20d"] is not None
