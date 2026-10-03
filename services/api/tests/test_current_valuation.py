from app.research.current_valuation import current_valuations


def test_current_screen_does_not_reuse_an_older_or_unverified_multiple():
    rows=[{"company_id":1,"snapshot_date":"2026-10-01","pe":20},
          {"company_id":2,"snapshot_date":"2026-10-02","pe":30},
          {"company_id":3,"snapshot_date":"2026-10-01","pe":40}]
    class Query:
        def select(self,*args): return self
        def eq(self,*args): return self
        def in_(self,*args): return self
        def execute(self): return type("Result",(),{"data":rows})()
    class Db:
        def table(self,name):
            assert name=="valuation_snapshots"
            return Query()
    candidates=[{"company_id":1,"price_date":"2026-10-02"},
                {"company_id":2,"price_date":"2026-10-02"},
                {"company_id":3,"price_date":"2026-10-01"},
                {"company_id":4,"price_date":"2026-10-02"}]
    result=current_valuations(Db(),candidates)
    assert set(result)=={2,3}
    assert result[2]["pe"]==30
