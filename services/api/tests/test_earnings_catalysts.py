from app.research.earnings_catalysts import catalyst_adjustment, recent_earnings


class FakeEarningsQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def select(self, *args):
        return self

    def in_(self, column, values):
        self.rows = [r for r in self.rows if r[column] in values]
        return self

    def eq(self, column, value):
        self.rows = [r for r in self.rows if r[column] == value]
        return self

    def gte(self, column, value):
        self.filters.append(("gte", column, value))
        self.rows = [r for r in self.rows if r[column] >= value]
        return self

    def lt(self, column, value):
        self.filters.append(("lt", column, value))
        self.rows = [r for r in self.rows if r[column] < value]
        return self

    def order(self, column, desc=False):
        self.rows.sort(key=lambda r: r[column], reverse=desc)
        return self

    def range(self, first, last):
        self.page = self.rows[first:last + 1]
        return self

    def execute(self):
        return type("Result", (), {"data": self.page})()


def test_recent_earnings_uses_each_price_date_and_ignores_old_reports():
    events = [
        {"company_id": 1, "reported_date": "2026-09-25", "source": "massive_benzinga"},
        {"company_id": 1, "reported_date": "2026-09-24", "source": "massive_benzinga"},
        {"company_id": 2, "reported_date": "2026-09-20", "source": "massive_benzinga"},
        {"company_id": 3, "reported_date": "2026-08-25", "source": "massive_benzinga"},
    ]

    class Db:
        def table(self, name):
            assert name == "earnings_events"
            self.query = FakeEarningsQuery(events)
            return self.query

    db = Db()
    got = recent_earnings(db, [
        {"company_id": 1, "price_date": "2026-09-25"},
        {"company_id": 2, "price_date": "2026-09-19"},
        {"company_id": 3, "price_date": "2026-09-25"},
    ])
    assert {cid: e["reported_date"] for cid, e in got.items()} == {1: "2026-09-24"}
    assert ("lt", "reported_date", "2026-09-25") in db.query.filters
    assert ("gte", "reported_date", "2026-08-20") in db.query.filters


def test_catalyst_adjustment_handles_missing_and_caps_outliers():
    assert catalyst_adjustment(None) == 0
    assert catalyst_adjustment({"surprise_percent": "10", "revenue_surprise_percent": -5}) == 1
    assert catalyst_adjustment({"surprise_percent": 100, "revenue_surprise_percent": 100}) == 8
