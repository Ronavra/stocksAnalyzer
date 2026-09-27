import pytest

from scripts.ingest_sec_fundamentals import upsert_company_metrics, validate_full_refresh


def test_company_filing_rows_use_one_upsert_request():
    calls=[]

    class Table:
        def upsert(self, rows, on_conflict, returning):
            calls.append((rows,on_conflict,returning))
            return self

        def execute(self):
            return None

    class Db:
        def table(self, name):
            assert name=="financial_metrics"
            return Table()

    filing={"period_end":"2026-06-30","filed_date":"2026-08-01","revenue":100}
    count=upsert_company_metrics(Db(),42,[filing],[filing],[filing],"2026-09-27T00:00:00Z")
    assert count==3
    assert len(calls)==1
    rows,conflict,returning=calls[0]
    assert conflict=="company_id,period_end,period_type"
    assert returning=="minimal"
    assert {r["period_type"] for r in rows}=={"annual","quarter","ttm"}
    assert all(r["company_id"]==42 and r["filed_date"]=="2026-08-01" for r in rows)


def test_full_refresh_rejects_empty_ttm_coverage():
    with pytest.raises(RuntimeError,match="TTM companies=0/503"):
        validate_full_refresh(503,503,0)
    with pytest.raises(RuntimeError,match="companies=100/503"):
        validate_full_refresh(503,100,400)
    validate_full_refresh(503,500,450)
