import pytest

from app.research.weekly_rank_metrics import (
    PROTOCOL, RANKER_VERSION, ROUND_TRIP_COST, executed_return, execution_dates,
    period_passes, ranker_is_validated, select_predictions, summarize_cohorts,
)


def passing_metrics():
    return {"cohorts": 30, "evaluation_coverage": 1., "mean_net_return": .02,
            "mean_excess_vs_spy": .01, "mean_improvement_vs_screen": .01,
            "stress_mean_excess_vs_spy": .007, "lower_bound_vs_spy": .002,
            "lower_bound_vs_screen": .002, "worst_20pct_mean": -.01,
            "screen_worst_20pct_mean": -.02, "downside_p10_breach_rate": .1}


def test_next_session_entry_uses_market_calendar_and_full_holding_period():
    calendar = ["2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30",
                "2026-10-01", "2026-10-02", "2026-10-05"]
    window = execution_dates(calendar, calendar[0])
    assert window == ("2026-09-28", "2026-10-05")
    # Friday's price gain is unavailable to a recommendation published Saturday.
    assert executed_return({calendar[0]: 10, window[0]: 20, window[1]: 21}, window) == pytest.approx(.05)
    assert executed_return({window[1]: 21}, window) is None
    assert execution_dates(calendar[:-1], calendar[0]) is None


def test_repeats_allowed_no_padding_and_risk_changes_order():
    predictions = [{"company_id": i, "expected_excess": e, "expected_return": .02, "downside_p10": q,
                    "feature_coverage": coverage, "previously_selected": True}
                   for i, e, q, coverage in ((1, .03, -.2, 1), (2, .02, -.02, 1),
                                           (3, -.01, -.01, 1), (4, .04, -.01, .5))]
    assert [p["company_id"] for p in select_predictions(predictions, "expected_excess")] == [1, 2]
    assert [p["company_id"] for p in select_predictions(predictions, "downside_aware")] == [2]
    predictions[1]["expected_return"] = -.01
    assert select_predictions(predictions, "downside_aware") == []
    many = [{"company_id": i, "expected_excess": .1, "expected_return": .1, "downside_p10": -.1, "feature_coverage": 1} for i in range(8)]
    assert len(select_predictions(many, "expected_excess", top=20)) == 5


def test_gate_rejects_weak_tail_cost_sensitivity_and_missing_evaluations():
    metrics = passing_metrics()
    assert period_passes(metrics)
    for key, value in (("cohorts", 25), ("lower_bound_vs_screen", -.001),
                       ("stress_mean_excess_vs_spy", -.001), ("worst_20pct_mean", -.03),
                       ("downside_p10_breach_rate", .4), ("evaluation_coverage", .9),
                       ("mean_net_return", float("nan"))):
        assert not period_passes({**metrics, key: value})
    report = {"evaluation_protocol": PROTOCOL, "primary_horizon_days": 5,
              "entry_policy": "next_session_close", "round_trip_cost": ROUND_TRIP_COST,
              "selection_rule": "middle_period_only", "selected_variant": "expected_excess",
              "selection_last_exit_date": "2026-01-01", "holdout_start": "2026-01-02",
              "selection": metrics, "holdout": metrics}
    run = {"status": "success", "model_version": RANKER_VERSION, "results": report}
    assert ranker_is_validated(run)
    assert not ranker_is_validated({**run, "results": {**report, "holdout": {**metrics, "lower_bound_vs_spy": -.001}}})
    assert not ranker_is_validated({**run, "status": "running"})
    assert not ranker_is_validated({**run, "results": {**report, "primary_horizon_days": 20}})
    assert not ranker_is_validated({**run, "results": {**report, "selection_last_exit_date": "2026-01-05"}})


def test_cash_week_has_no_trading_cost_and_is_not_silently_removed():
    report = summarize_cohorts([{"model_return": 0, "screen_return": -.01,
                                 "spy_return": -.02, "picks": []}])
    assert report["cohorts"] == 1
    assert report["mean_net_return"] == 0
    assert report["mean_excess_vs_spy"] == .02
    assert report["downside_p10_breach_rate"] is None
