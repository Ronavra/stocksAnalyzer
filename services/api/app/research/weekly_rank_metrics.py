"""Execution and promotion rules shared by the weekly experiment and production."""

from math import isfinite
from random import Random
from statistics import mean

RANKER_VERSION = "weekly-top-five-v1"
PROTOCOL = "weekly_next_close_5d_selection_holdout_v1"
HORIZON = 5
TOP = 5
ROUND_TRIP_COST = .002  # Scenario assumption: 20 basis points, not a broker quote.
STRESS_COST = .005
MIN_COVERAGE = .8
MIN_WEEKS = 26


def number(value):
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def execution_dates(calendar, anchor, horizon=HORIZON):
    """A recommendation after anchor's close enters at the next session's close."""
    try:
        index = calendar.index(anchor)
    except ValueError:
        return None
    if index + 1 + horizon >= len(calendar):
        return None
    return calendar[index + 1], calendar[index + 1 + horizon]


def executed_return(prices, dates):
    if dates is None:
        return None
    entry = number(prices.get(dates[0]))
    exit_price = number(prices.get(dates[1]))
    if entry is None or entry <= 0 or exit_price is None or exit_price <= 0:
        return None
    return exit_price / entry - 1


def ranking_score(expected_excess, downside_p10, variant):
    if variant == "expected_excess":
        return expected_excess
    if variant == "downside_aware":
        return expected_excess - .25 * max(0., -downside_p10)
    raise ValueError(f"Unknown ranker variant: {variant}")


def select_predictions(predictions, variant, top=TOP):
    # No previous-week exclusion, sector quota, or padding to five.
    eligible = [p for p in predictions if
                p.get("feature_coverage", 0) >= MIN_COVERAGE
                and number(p.get("expected_excess")) is not None
                and number(p.get("expected_return")) is not None
                and number(p.get("downside_p10")) is not None
                and p["expected_excess"] > 0
                and p["expected_return"] > ROUND_TRIP_COST
                and ranking_score(p["expected_excess"], p["downside_p10"], variant) > 0]
    return sorted(eligible, key=lambda p: (
        -ranking_score(p["expected_excess"], p["downside_p10"], variant),
        str(p["company_id"])))[:min(top, TOP)]


def tail_mean(values):
    return mean(sorted(values)[:max(1, (len(values) + 4) // 5)]) if values else None


def block_lower_bound(values, block=4, repeats=1000):
    """One-sided 95% circular block bootstrap; nearby weeks stay together."""
    if not values:
        return None
    rng = Random(42)
    samples = []
    for _ in range(repeats):
        draws = []
        while len(draws) < len(values):
            start = rng.randrange(len(values))
            draws.extend(values[(start + i) % len(values)] for i in range(block))
        samples.append(mean(draws[:len(values)]))
    return sorted(samples)[int(.05 * repeats)]


def summarize_cohorts(cohorts):
    if not cohorts:
        return {"cohorts": 0}
    net = [c["model_return"] - (ROUND_TRIP_COST if c["picks"] else 0.) for c in cohorts]
    # Paired comparison: both stock strategies pay identical cost assumptions.
    vs_screen = [c["model_return"] - (ROUND_TRIP_COST if c["picks"] else 0.)
                 - (c["screen_return"] - ROUND_TRIP_COST) for c in cohorts]
    vs_spy = [net[i] - c["spy_return"] for i, c in enumerate(cohorts)]
    stress = [c["model_return"] - (STRESS_COST if c["picks"] else 0.) - c["spy_return"] for c in cohorts]
    breaches = [p["actual_return"] < p["downside_p10"]
                for c in cohorts for p in c["picks"]]
    return {
        "cohorts": len(cohorts), "picks": sum(len(c["picks"]) for c in cohorts),
        "mean_net_return": mean(net), "mean_excess_vs_spy": mean(vs_spy),
        "mean_improvement_vs_screen": mean(vs_screen),
        "stress_mean_excess_vs_spy": mean(stress),
        "beat_spy_week_rate": mean(x > 0 for x in vs_spy),
        "loss_week_rate": mean(x < 0 for x in net),
        "worst_week": min(net), "worst_20pct_mean": tail_mean(net),
        "screen_worst_20pct_mean": tail_mean([c["screen_return"] - ROUND_TRIP_COST for c in cohorts]),
        "lower_bound_vs_spy": block_lower_bound(vs_spy),
        "lower_bound_vs_screen": block_lower_bound(vs_screen),
        "downside_p10_breach_rate": mean(breaches) if breaches else None,
    }


def period_passes(metrics):
    required = ("mean_net_return", "mean_excess_vs_spy", "mean_improvement_vs_screen",
                "stress_mean_excess_vs_spy", "lower_bound_vs_spy", "lower_bound_vs_screen",
                "worst_20pct_mean", "screen_worst_20pct_mean", "downside_p10_breach_rate")
    if (metrics.get("cohorts", 0) < MIN_WEEKS
            or metrics.get("evaluation_coverage", 0) < .95
            or any(number(metrics.get(k)) is None for k in required)):
        return False
    return (all(metrics[k] > 0 for k in required[:6])
            and metrics["worst_20pct_mean"] >= metrics["screen_worst_20pct_mean"]
            and .05 <= metrics["downside_p10_breach_rate"] <= .20)


def ranker_is_validated(run):
    report = (run or {}).get("results") or {}
    return bool(run and run.get("status") == "success"
                and run.get("model_version") == RANKER_VERSION
                and report.get("evaluation_protocol") == PROTOCOL
                and report.get("primary_horizon_days") == HORIZON
                and report.get("entry_policy") == "next_session_close"
                and report.get("round_trip_cost") == ROUND_TRIP_COST
                and report.get("selected_variant") in ("expected_excess", "downside_aware")
                and report.get("selection_rule") == "middle_period_only"
                and period_passes(report.get("selection") or {})
                and period_passes(report.get("holdout") or {}))
