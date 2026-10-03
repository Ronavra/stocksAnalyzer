from datetime import date, timedelta

from app.research import weekly_ranker as ranker
from test_weekly_rank_metrics import passing_metrics


def test_training_purges_labels_until_delayed_exit_is_known():
    records = [{"target_excess": .01, "label_end_date": day} for day in ("2026-10-01", "2026-10-02", "2026-10-05")]
    records.append({"target_excess": None, "label_end_date": "2026-09-01"})
    assert ranker.training_before(records, "2026-10-02") == records[:1]


def test_missing_outcomes_do_not_remove_stock_before_selection():
    predictions = [{"company_id": i, "screen_score": 100-i, "expected_excess": .1-i*.001, "expected_return": .1,
                    "downside_p10": -.1, "feature_coverage": 1., "actual_return": None if i == 1 else .01,
                    "spy_return": .005} for i in range(1, 8)]
    metrics, cohorts = ranker.evaluate({"2026-09-25": predictions}, "expected_excess")
    assert cohorts == []
    assert metrics["excluded"]["missing_selected_outcome"] == 1


def test_holdout_cannot_choose_variant(monkeypatch):
    dates = [(date(2020, 1, 3)+timedelta(weeks=i)).isoformat() for i in range(200)]
    records = [{"date": day, "target_excess": .01} for day in dates]
    boundary = dates[160]
    calls = []
    monkeypatch.setattr(ranker, "walk_forward", lambda rows, days: {"first": days[0]})

    def evaluate(outputs, variant):
        calls.append((outputs["first"], variant))
        # Selection prefers expected_excess; holdout would prefer the other variant.
        improvement = .02 if variant == "expected_excess" else .01
        if outputs["first"] == boundary:
            improvement = -.01 if variant == "expected_excess" else .2
        return {**passing_metrics(), "mean_improvement_vs_screen": improvement}, []

    monkeypatch.setattr(ranker, "evaluate", evaluate)
    result = ranker.validate({"records": records, "latest_date": dates[-1]})
    assert result["selected_variant"] == "expected_excess"
    assert result["holdout"]["mean_improvement_vs_screen"] == -.01
    assert (boundary, "downside_aware") not in calls
