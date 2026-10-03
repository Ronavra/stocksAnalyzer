from datetime import date

from app.providers.sec import facts_by_period, quarter_facts_by_period, latest_financial_report, shares_outstanding_by_period
from app.research.financial_quality import CORE_FIELDS, company_quality, summarize_quality
from app.research.fundamentals import derive
from scripts.ingest_sec_fundamentals import build_ttm_rows


def fact(start, end, value, filed="2026-08-01", form="10-Q", fp="Q2"):
    return {"start":start,"end":end,"val":value,"filed":filed,"form":form,"fp":fp}


def test_alias_changes_do_not_hide_latest_income_statement():
    old=fact("2025-01-01","2025-03-31",80,"2025-05-01",fp="Q1")
    new=fact("2026-04-01","2026-06-30",100)
    data={"facts":{"us-gaap":{
        "RevenueFromContractWithCustomerExcludingAssessedTax":{"units":{"USD":[old]}},
        "Revenues":{"units":{"USD":[new]}},
        "NetIncomeLoss":{"units":{"USD":[old,new]}},
    }}}
    latest=quarter_facts_by_period(data)[0]
    assert latest["period_end"]=="2026-06-30"
    assert latest["revenue"]==100


def test_bank_total_revenue_is_not_replaced_by_contract_fees():
    total=fact("2026-04-01","2026-06-30",100)
    fees=fact("2026-04-01","2026-06-30",20,"2026-08-02")
    data={"facts":{"us-gaap":{
        "RevenuesNetOfInterestExpense":{"units":{"USD":[total]}},
        "RevenueFromContractWithCustomerExcludingAssessedTax":{"units":{"USD":[fees]}},
        "NetIncomeLoss":{"units":{"USD":[fees]}},
    }}}
    assert quarter_facts_by_period(data)[0]["revenue"]==100


def test_filing_fp_does_not_filter_quarter_facts_in_an_annual_report():
    quarter=fact("2025-10-01","2025-12-31",100,"2026-02-01","10-K","FY")
    data={"facts":{"us-gaap":{tag:{"units":{"USD":[quarter]}} for tag in ("Revenues","NetIncomeLoss")}}}
    assert quarter_facts_by_period(data)[0]["revenue"]==100
    assert facts_by_period(data)==[]


def test_missing_debt_component_and_cash_are_not_zero():
    quarter=fact("2026-04-01","2026-06-30",100)
    data={"facts":{"us-gaap":{tag:{"units":{"USD":[quarter]}} for tag in ("Revenues","NetIncomeLoss","LongTermDebtNoncurrent")}}}
    assert quarter_facts_by_period(data)[0].get("total_debt") is None
    assert derive({"free_cash_flow":10,"total_debt":100},None).net_debt_to_fcf is None
    assert derive({"free_cash_flow":10,"cash":0},None).net_debt_to_fcf is None
    assert derive({"free_cash_flow":10,"total_debt":100,"cash":0},None).net_debt_to_fcf==10


def test_shares_fallback_is_not_hidden_by_old_dei_facts():
    old={"end":"2021-12-31","val":10,"filed":"2022-02-01","form":"10-K"}
    new={"end":"2026-06-30","val":20,"filed":"2026-08-01","form":"10-Q"}
    data={"facts":{"dei":{"EntityCommonStockSharesOutstanding":{"units":{"shares":[old]}}},
                   "us-gaap":{"CommonStockSharesOutstanding":{"units":{"shares":[new]}}}}}
    assert shares_outstanding_by_period(data)["2026-06-30"]["shares_outstanding"]==20


def test_annual_statement_remains_ttm_without_four_quarters():
    annual={"period_end":"2025-12-31","filed_date":"2026-02-01","revenue":400,"net_income":40,"eps_diluted":1.03}
    assert build_ttm_rows([annual],[])==[annual]


def test_missing_quarter_cannot_create_an_inflated_ttm():
    quarters=[{"period_end":end,"revenue":100,"net_income":10} for end in
              ("2025-03-31","2025-06-30","2025-12-31","2026-03-31")]
    assert build_ttm_rows([],quarters)==[]


def test_actual_q4_and_reported_annual_eps_are_preserved():
    annual={"period_end":"2025-12-31","filed_date":"2026-02-01","revenue":400,"net_income":40,"eps_diluted":1.03}
    quarters=[{"period_end":end,"revenue":100,"net_income":10,"eps_diluted":.25,"filed_date":"2026-02-01"}
              for end in ("2025-03-31","2025-06-30","2025-09-30","2025-12-31","2026-03-31")]
    quarters[3]["eps_diluted"]=.27
    ttm=build_ttm_rows([annual],quarters)
    assert next(x for x in ttm if x["period_end"]=="2025-12-31")["eps_diluted"]==1.03
    assert abs(ttm[-1]["eps_diluted"]-1.02)<1e-8


def test_latest_filing_is_selected_by_report_period_before_filing_date():
    submissions={"filings":{"recent":{
        "form":["8-K","10-Q","10-K/A"],"reportDate":["2026-09-30","2026-06-30","2025-12-31"],
        "filingDate":["2026-10-01","2026-08-01","2026-09-01"],
    }}}
    assert latest_financial_report(submissions)=={"period_end":"2026-06-30","filed_date":"2026-08-01","form":"10-Q"}


def test_successful_download_is_separate_from_latest_filing_and_completeness():
    company={"id":1,"ticker":"AAA"}; report={"period_end":"2026-06-30"}
    old={"period_end":"2025-12-31","revenue":100,"net_income":10}
    gap=company_quality(company,[old],[],[old],report,date(2026,10,3))
    assert gap["status"]=="extraction_behind_latest_filing"
    current={"period_end":"2026-06-30",**{k:0 for k in CORE_FIELDS}}
    current.pop("total_debt")
    partial=company_quality(company,[],[current],[current],report,date(2026,10,3))
    assert partial["status"]=="current" and partial["missing_fields"]==["total_debt"]
    summary=summarize_quality([gap,partial])
    assert summary["current_ttm"]==1 and summary["current_complete"]==0
    assert not summary["all_current"] and not summary["all_current_and_complete"]


def test_latest_quarter_without_full_ttm_history_is_reported():
    company={"id":1,"ticker":"NEW"}; quarter={"period_end":"2026-06-30"}
    report={"period_end":"2026-06-30"}
    assert company_quality(company,[],[quarter],[],report,date(2026,10,3))["status"]=="insufficient_ttm_history"
