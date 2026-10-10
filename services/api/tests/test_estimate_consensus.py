from app.providers.estimate_consensus import normalize

OBSERVED = "2026-10-10T14:00:00+00:00"


def record(**values):
    return {"period": "0y", "endDate": "2027-01-31",
            "earningsEstimate": {"avg": {"raw": 0}, "low": {"raw": -1}, "high": {"raw": 2}, "numberOfAnalysts": {"raw": 3}, "earningsCurrency": "USD"},
            "revenueEstimate": {"avg": {"raw": 200}, "numberOfAnalysts": {"raw": 4}, "revenueCurrency": "USD"}, **values}


def test_actual_fiscal_date_zero_eps_and_accounting_basis_are_preserved():
    row = normalize(1, [record()], OBSERVED)[0]
    assert row["fiscal_period_end"] == "2027-01-31"
    assert row["eps_consensus"] == 0 and row["eps_low"] == -1
    assert row["eps_basis"] == "unknown" and row["eps_currency"] == "USD"
    assert row["captured_at"] == OBSERVED and row["captured_date"] == "2026-10-10"
    assert row["eps_analyst_count"] == 3 and row["revenue_analyst_count"] == 4


def test_missing_fiscal_date_and_unrecognized_relative_period_are_not_guessed():
    assert normalize(1, [record(endDate=None), record(period="+2y"), record(endDate="2000-01-01")], OBSERVED) == []


def test_nan_empty_estimates_and_reversed_intervals_remain_unknown():
    empty = record(earningsEstimate={"avg": {"raw": float("nan")}}, revenueEstimate={})
    assert normalize(1, [empty], OBSERVED) == []
    row = normalize(1, [record(earningsEstimate={"avg": {"raw": 2}, "low": {"raw": 4}, "high": {"raw": 1}})], OBSERVED)[0]
    assert row["eps_consensus"] == 2 and row["eps_low"] is None and row["eps_high"] is None


def test_provider_retrospective_trend_keeps_todays_observation_time():
    row = normalize(1, [record(epsTrend={"30daysAgo": {"raw": 1}, "current": {"raw": 2}}, epsRevisions={"upLast30days": {"raw": 3}})], OBSERVED)[0]
    assert row["provider_eps_trend"] == {"30daysAgo": 1., "current": 2.}
    assert row["provider_eps_revisions"]["upLast30days"] == 3
    assert row["captured_at"] == OBSERVED


def test_duplicate_fiscal_periods_are_deduplicated_before_bulk_write():
    rows = normalize(1, [record(), record(), record(period="0q", endDate="2026-10-31")], OBSERVED)
    assert len(rows) == 2 and {r["period_type"] for r in rows} == {"annual", "quarter"}
