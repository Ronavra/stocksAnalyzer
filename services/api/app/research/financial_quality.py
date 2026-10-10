"""Separate successful retrieval, latest-filing coverage and field completeness."""

from datetime import date
from collections import Counter

CORE_FIELDS=("revenue","net_income","eps_diluted","operating_income",
             "free_cash_flow","cash","total_debt","shares_outstanding")
MAX_TTM_AGE_DAYS=180


def company_quality(company,annual,quarters,ttm,latest_report,asof=None):
    asof=asof or date.today()
    latest_ttm=max(ttm,key=lambda r:r["period_end"]) if ttm else None
    latest_parsed=max([r["period_end"] for r in annual+quarters],default=None)
    expected=(latest_report or {}).get("period_end")
    missing=[k for k in CORE_FIELDS if not latest_ttm or latest_ttm.get(k) is None]
    is_bank=company.get('scoring_profile')=='bank' or company.get('industry') in ('Diversified Banks','Regional Banks')
    required=[k for k in CORE_FIELDS if not is_bank or k not in ('operating_income','free_cash_flow','total_debt')]
    required_missing=[k for k in required if not latest_ttm or latest_ttm.get(k) is None]
    if is_bank:
        required_missing.extend(k for k in ('equity','cet1_ratio') if ((latest_ttm or {}).get('supplemental') or {}).get(k) is None)
    period=latest_ttm["period_end"] if latest_ttm else None
    age=(asof-date.fromisoformat(period)).days if period else None
    if not latest_report:
        status="filing_check_unavailable"
    elif not latest_parsed or latest_parsed<expected:
        status="extraction_behind_latest_filing"
    elif not period:
        status="insufficient_ttm_history"
    elif (period<expected or ((latest_report or {}).get("filed_date")
            and ((latest_ttm or {}).get("filed_date") or "")<latest_report.get('financial_statement_base_filed_date',latest_report["filed_date"]))):
        status="ttm_behind_latest_filing"
    elif age is None or not 0<=age<=MAX_TTM_AGE_DAYS:
        status="ttm_period_old"
    else:
        status="current"
    return {"ticker":company["ticker"],"company_id":company["id"],"status":status,
            "latest_report":latest_report,"latest_parsed_period":latest_parsed,
            "ttm_period":period,"ttm_filed_date":(latest_ttm or {}).get("filed_date"),
            "ttm_age_days":age,"missing_fields":missing,"core_complete":not missing,
            "required_profile":'bank' if is_bank else 'general','missing_required_fields':required_missing,
            "profile_complete":not required_missing}


def summarize_quality(rows):
    counts=Counter(r["status"] for r in rows)
    return {"universe_checked":len(rows),"status_counts":dict(counts),
            "current_ttm":counts.get("current",0),
            "current_complete":sum(r["status"]=="current" and r.get("core_complete",False) for r in rows),
            "current_profile_complete":sum(r['status']=='current' and r.get('profile_complete',r.get('core_complete',False)) for r in rows),
            "field_coverage":{k:sum(r.get("ttm_period") is not None and k not in r.get("missing_fields",CORE_FIELDS) for r in rows) for k in CORE_FIELDS},
            "filing_fallback_used":sum(bool(r.get("filing_fallback_used")) for r in rows),
            "filing_fallback_failed":sum(bool(r.get("filing_fallback_error")) for r in rows),
            "bank_coverage":{"companies":sum(bool(r.get("bank_profile")) for r in rows),
                             "equity":sum(bool((r.get("bank_metrics") or {}).get("equity")) for r in rows if r.get("bank_profile")),
                             "cet1_ratio":sum(bool((r.get("bank_metrics") or {}).get("cet1_ratio")) for r in rows if r.get("bank_profile"))},
            "all_current":bool(rows) and counts.get("current",0)==len(rows),
            "all_current_and_complete":bool(rows) and all(r["status"]=="current" and r.get("core_complete",False) for r in rows)}
