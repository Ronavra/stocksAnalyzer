from datetime import datetime, timezone
from app.research.source_coverage import company_coverage, summarize, load_coverage

NOW = datetime(2026, 10, 10, 14, tzinfo=timezone.utc)


def layers(raw, audit=None, checked=None):
    company = company_coverage({"company_id": 1, "ticker": "TEST", **raw}, audit, checked, NOW)
    assert not company["all_major_data_complete"]
    return {x["key"]: x for x in company["layers"]}


def test_fresh_market_data_does_not_imply_complete_evidence():
    result = layers({"price_date": "2026-10-09", "feature_date": "2026-10-09"})
    assert result["market"]["status"] == "current"
    assert result["financials"]["status"] == "missing"
    assert result["macro"]["status"] == "not_collected"
    assert result["news"]["status"] == "unknown"


def test_successful_recent_retrieval_does_not_make_old_financial_period_current():
    result = layers({"financial": {"period_end": "2024-12-31", "observed_at": NOW.isoformat()}},
                    {"status": "ttm_behind_latest_filing", "missing_fields": []}, NOW.isoformat())
    assert result["financials"]["status"] == "stale"


def test_current_financial_audit_requires_fresh_check_and_reports_missing_fields():
    raw = {"financial": {"period_end": "2026-06-30"}}
    assert layers(raw, {"status": "current"}, "2026-10-01T14:00:00+00:00")["financials"]["status"] == "stale"
    assert layers(raw, {"status": "current", "missing_fields": ["free_cash_flow"]}, NOW.isoformat())["financials"]["status"] == "partial"


def test_first_estimate_snapshot_is_not_a_revision_archive():
    result = layers({"estimates": {"observed_at": NOW.isoformat(), "eps_periods": 4, "revenue_periods": 4, "observation_days": 1}})
    assert result["estimates"]["status"] == "current"
    assert result["revisions"]["status"] == "building"


def test_inconsistent_provider_interval_is_flagged_as_partial():
    result = layers({"estimates": {"observed_at": NOW.isoformat(), "eps_periods": 4, "revenue_periods": 4, "inconsistent_periods": 1}})
    assert result["estimates"]["status"] == "partial"
    assert "1 inconsistent provider intervals" in result["estimates"]["detail"]


def test_future_timestamps_are_not_counted_as_current():
    result = layers({"estimates": {"observed_at": "2026-10-11T14:00:00Z", "eps_periods": 4, "revenue_periods": 4}})
    assert result["estimates"]["status"] != "current"


def test_guidance_pending_or_failed_does_not_mean_no_company_guidance():
    result = layers({"disclosures": {"pending": 3, "errors": 1}})
    assert result["guidance"]["status"] == "pending"
    assert "1 parse failures" in result["guidance"]["detail"]


def test_summary_distinguishes_observed_and_current_from_partial_data():
    raw = {"company_id": 1, "ticker": "TEST", "news": {"articles_90d": 1}}
    company = company_coverage(raw, now=NOW)
    families = {f["key"]: f for f in summarize([company])}
    assert families["news"]["covered_companies"] == 1
    assert families["guidance"]["covered_companies"] == 0
    assert families["macro"]["status_counts"] == {"not_collected": 1}


def test_several_earnings_only_runs_do_not_hide_recent_financial_audit():
    from types import SimpleNamespace
    audit={"status":"current","company_id":1,"missing_fields":[]}
    older={"pipeline":"research_sources_refresh","status":"success","finished_at":NOW.isoformat(),"metadata":{"financial_audit":{"companies":[audit]}}}
    reports=[{"pipeline":"research_sources_refresh","status":"success","finished_at":NOW.isoformat(),"metadata":{"earnings":"refreshed"}} for _ in range(4)]+[older]
    class Query:
        def __init__(self): self.rows=reports; self.inventory=False
        def select(self,*args): return self
        def eq(self,*args): return self
        def order(self,*args,**kwargs): return self
        def in_(self,*args): return self
        def contains(self,column,value):
            self.rows=[r for r in self.rows if "financial_audit" in r["metadata"]]
            return self
        def limit(self,n): self.rows=self.rows[:n]; return self
        def execute(self):
            if self.inventory:
                return SimpleNamespace(data=[{"company_id":1,"ticker":"TEST","financial":{"period_end":"2026-06-30"}}])
            return SimpleNamespace(data=self.rows)
    class Db:
        def table(self,name): return Query()
        def rpc(self,name,params):
            query=Query(); query.inventory=True; return query
    coverage=load_coverage(Db(),now=NOW)
    financial=next(x for x in coverage["companies"][0]["layers"] if x["key"]=="financials")
    assert financial["status"]=="current"
