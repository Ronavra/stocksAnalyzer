import asyncio
from datetime import date
from app.providers.sec import facts_by_period, quarter_facts_by_period
from scripts.ingest_sec_fundamentals import build_ttm_rows, recover_filing_history


COMPANY={"id":1,"ticker":"TEST","cik":"1000"}


def statement(start,end,form,filed,value):
    row={"start":start,"end":end,"form":form,"filed":filed,"val":value}
    return {"facts":{"us-gaap":{tag:{"units":{"USD":[row.copy()]}} for tag in ("Revenues","NetIncomeLoss")}}}


def filings(count=3):
    return {"filings":{"recent":{
        "form":["10-Q"]*count,"reportDate":["2026-06-30","2026-03-31","2025-12-31","2025-09-30","2025-06-30","2025-03-31"][:count],
        "filingDate":["2026-08-01","2026-05-01","2026-02-01","2025-11-01","2025-08-01","2025-05-01"][:count],
        "accessionNumber":[f"0000001000-26-{i:06}" for i in range(count)],
    }}}


def test_previous_filing_recovers_ttm_when_latest_quarter_is_already_parsed():
    from app.providers.sec import merge_company_facts
    data=statement("2025-01-01","2025-12-31","10-K","2026-02-01",400)
    for start,end in (("2025-01-01","2025-03-31"),("2025-04-01","2025-06-30"),("2025-07-01","2025-09-30"),("2026-04-01","2026-06-30")):
        data=merge_company_facts(data,statement(start,end,"10-Q","2026-08-01",100))
    assert quarter_facts_by_period(data)[0]["period_end"]=="2026-06-30"
    assert build_ttm_rows(facts_by_period(data),quarter_facts_by_period(data))[-1]["period_end"]=="2025-12-31"
    calls=[]
    class Provider:
        async def filing_facts(self,cik,report):
            calls.append(report["period_end"])
            return statement("2026-01-01","2026-03-31","10-Q","2026-05-01",120) if report["period_end"]=="2026-03-31" else {"facts":{}}
    _,annual,quarterly,recovered,errors=asyncio.run(recover_filing_history(Provider(),COMPANY,data,filings(),10,16,date(2026,10,5)))
    latest=build_ttm_rows(annual,quarterly)[-1]
    assert latest["period_end"]=="2026-06-30" and latest["revenue"]==420
    assert calls==["2026-06-30","2026-03-31"] and len(recovered)==2 and not errors


def test_current_ttm_does_not_download_redundant_filing_instances():
    data=statement("2025-07-01","2026-06-30","10-K","2026-08-01",400)
    submissions={"filings":{"recent":{"form":["10-K"],"reportDate":["2026-06-30"],"filingDate":["2026-08-01"],"accessionNumber":["0000001000-26-000001"]}}}
    class Provider:
        async def filing_facts(self,*args):
            raise AssertionError("Unexpected redundant request")
    _,_,_,recovered,errors=asyncio.run(recover_filing_history(Provider(),COMPANY,data,submissions,10,16,date(2026,10,5)))
    assert not recovered and not errors


def test_unavailable_history_is_bounded_and_preserves_missing_ttm():
    class Provider:
        async def filing_facts(self,*args):
            raise RuntimeError("No instance document")
    _,annual,quarterly,recovered,errors=asyncio.run(recover_filing_history(Provider(),COMPANY,{"facts":{}},filings(6),10,16))
    assert len(errors)==5 and not recovered and build_ttm_rows(annual,quarterly)==[]
