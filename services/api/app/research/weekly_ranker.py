"""Five-day cross-sectional return ranking with an independent downside forecast.

Prices/context only: revised earnings and current financial backfills do not train
this experiment. The report explicitly records the current-constituent limitation.
"""

from datetime import date, timedelta
from statistics import mean

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from app.research.calibrated_model import BASE_PRICE_FEATURES, CONTEXT_FEATURES, _derived_price_context, load_price_rows
from app.research.weekly_backtest import historical_catalyst, last_trading_day_of_weeks, setup_at
from app.research.earnings_catalysts import catalyst_adjustment
from app.research.weekly_rank_metrics import (
    HORIZON, MIN_COVERAGE, PROTOCOL, RANKER_VERSION, ROUND_TRIP_COST,
    execution_dates, executed_return, number, period_passes, ranking_score,
    select_predictions, summarize_cohorts,
)

FEATURES = BASE_PRICE_FEATURES + CONTEXT_FEATURES
VARIANTS = ("expected_excess", "downside_aware")


def prepare(db, years=5, point_in_time=False):
    rows, latest = load_price_rows(db, years)
    companies = {r["id"]: r for r in db.table("companies").select("id,ticker,sector,is_sp500").execute().data or []}
    spy_id = next((cid for cid, c in companies.items() if c["ticker"] == "SPY"), None)
    if spy_id is None:
        raise RuntimeError("Weekly ranker requires SPY prices")
    if point_in_time:
        from .observations import member_asof
        from .financial_ranking import paged
        memberships=paged(lambda a,b:db.table("index_memberships").select("company_id,effective_from,effective_to,captured_at")
                          .eq("index_code","SP500").order("id").range(a,b))
        known_ids={r["company_id"] for r in memberships}|{spy_id}
        rows=[r for r in rows if r["company_id"] in known_ids]
    else:
        rows = [r for r in rows if r["company_id"] == spy_id or companies.get(r["company_id"], {}).get("is_sp500")]
    spy_rows = sorted([r for r in rows if r["company_id"] == spy_id], key=lambda r: r["feature_date"])
    calendar = [r["feature_date"] for r in spy_rows]
    if not latest or not calendar or calendar[-1] != latest:
        raise RuntimeError("Weekly ranker requires a current SPY benchmark")
    cutoff = (date.fromisoformat(latest) - timedelta(days=365 * years)).isoformat()
    anchors = last_trading_day_of_weeks(spy_rows, cutoff)
    # Latest prediction is allowed on a non-Friday manual research run as well.
    dates = set(anchors) | {latest}
    if point_in_time:
        context,by_company=_derived_price_context(rows,companies,dates,
            eligible=lambda cid,day:cid==spy_id or member_asof(memberships,cid,day))
    else:
        context, by_company = _derived_price_context(rows, companies, dates)
    price_maps = {cid: {r["feature_date"]: r.get("close") for r in items} for cid, items in by_company.items()}
    records = []
    for cid, items in by_company.items():
        if cid == spy_id:
            continue
        for i, row in enumerate(items):
            anchor = row["feature_date"]
            if point_in_time and not member_asof(memberships,cid,anchor):
                continue
            if anchor not in dates or number(row.get("close")) is None or number(row.get("close")) <= 0:
                continue
            fd = {k: number(row.get(k)) for k in BASE_PRICE_FEATURES}
            fd.update(context.get((cid, anchor), {}))
            coverage = sum(number(fd.get(k)) is not None for k in FEATURES) / len(FEATURES)
            if coverage < MIN_COVERAGE:
                continue
            execution = execution_dates(calendar, anchor)
            actual = executed_return(price_maps[cid], execution)
            benchmark = executed_return(price_maps[spy_id], execution)
            records.append({
                "company_id": cid, "date": anchor, "selection_close":number(row.get("close")), "features": fd, "feature_coverage": coverage,
                "actual_return": actual, "spy_return": benchmark,
                "target_excess": actual - benchmark if actual is not None and benchmark is not None else None,
                "label_end_date": execution[1] if execution else None,
                "setup": setup_at(items, i),
            })
    events = []
    offset = 0
    while True:
        page = (db.table("earnings_events").select("company_id,reported_date,surprise_percent,revenue_surprise_percent")
                .eq("source", "massive_benzinga").gte("reported_date", cutoff)
                .order("reported_date").range(offset, offset + 999).execute().data or [])
        events.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    earnings = {}
    for event in events:
        earnings.setdefault(event["company_id"], []).append(event)
    for record in records:
        setup = record["setup"]
        event = historical_catalyst(earnings.get(record["company_id"], []), record["date"])
        record["historical_earnings"]=event
        if setup and setup["sample_size"] >= 50 and setup["up"] >= .52 and setup["median"] > 0:
            record["screen_score"] = setup["score"] + catalyst_adjustment(event)
        else:
            record["screen_score"] = None
    return {"records": records, "latest_date": latest, "anchors": anchors, "companies": companies}


def training_before(records, boundary):
    # Purge by actual exit date, including the additional entry session.
    return [r for r in records if r["target_excess"] is not None
            and r["label_end_date"] < boundary]


def matrix(records):
    return np.asarray([[np.nan if number(r["features"].get(k)) is None else float(r["features"][k])
                        for k in FEATURES] for r in records], dtype=float)


def fit(records):
    if len(records) < 5000 or len({r["date"] for r in records}) < 52:
        raise RuntimeError("Insufficient matured weekly ranker training history")
    common = dict(max_depth=3, max_iter=100, learning_rate=.05, l2_regularization=2.,
                  min_samples_leaf=80, random_state=42, early_stopping=False)
    expected = HistGradientBoostingRegressor(**common)
    absolute = HistGradientBoostingRegressor(**common)
    downside = HistGradientBoostingRegressor(loss="quantile", quantile=.1, **common)
    x = matrix(records)
    # Every weekly cross-section receives equal weight despite missing tickers.
    counts = {}
    for r in records:
        counts[r["date"]] = counts.get(r["date"], 0) + 1
    weights = np.asarray([len(records) / (len(counts) * counts[r["date"]]) for r in records])
    expected.fit(x, np.asarray([r["target_excess"] for r in records]), sample_weight=weights)
    absolute.fit(x, np.asarray([r["actual_return"] for r in records]), sample_weight=weights)
    downside.fit(x, np.asarray([r["actual_return"] for r in records]), sample_weight=weights)
    return expected, downside, absolute


def predict(models, records):
    if not records:
        return []
    x = matrix(records)
    expected = models[0].predict(x)
    downside = models[1].predict(x)
    absolute = models[2].predict(x)
    return [{**r, "expected_excess": float(e), "downside_p10": float(q), "expected_return": float(a)}
            for r, e, q, a in zip(records, expected, downside, absolute)]


def walk_forward(records, dates):
    by_date = {}
    for r in records:
        by_date.setdefault(r["date"], []).append(r)
    outputs = {}
    models = None
    for index, anchor in enumerate(dates):
        if models is None or index % 13 == 0:
            train = training_before(records, anchor)
            print(f"Weekly ranker fit before {anchor}: {len(train)} matured rows", flush=True)
            models = fit(train)
        outputs[anchor] = predict(models, by_date.get(anchor, []))
    return outputs


def evaluate(outputs, variant):
    cohorts = []
    excluded = {"no_screen_candidates": 0, "missing_selected_outcome": 0}
    for anchor, predictions in outputs.items():
        screen = sorted([p for p in predictions if p["screen_score"] is not None],
                        key=lambda p: (-p["screen_score"], str(p["company_id"])))[:5]
        picks = select_predictions(predictions, variant)
        if not screen:
            excluded["no_screen_candidates"] += 1
            continue
        # Outcomes never determine which ticker enters either shortlist.
        if any(p["actual_return"] is None or p["spy_return"] is None for p in screen + picks):
            excluded["missing_selected_outcome"] += 1
            continue
        cohorts.append({"date": anchor, "model_return": mean(p["actual_return"] for p in picks) if picks else 0.,
                        "screen_return": mean(p["actual_return"] for p in screen),
                        "spy_return": screen[0]["spy_return"],
                        "picks": [{k: p[k] for k in ("company_id", "actual_return", "expected_return", "expected_excess", "downside_p10")} for p in picks]})
    metrics = summarize_cohorts(cohorts)
    metrics["attempted_cohorts"] = len(outputs)
    metrics["excluded"] = excluded
    metrics["evaluation_coverage"] = len(cohorts) / len(outputs) if outputs else 0.
    return metrics, cohorts


def validate(prepared):
    records = prepared["records"]
    mature_dates = sorted({r["date"] for r in records if r["target_excess"] is not None})
    if len(mature_dates) < 180:
        raise RuntimeError("At least 180 matured weekly cross-sections are required")
    first = int(len(mature_dates) * .6)
    second = int(len(mature_dates) * .8)
    holdout_dates = mature_dates[second:]
    end_dates = {r["date"]: r["label_end_date"] for r in records if r["target_excess"] is not None}
    # Variant choice must be possible before the first holdout recommendation.
    # The last selection week's delayed exit can cross this boundary.
    selection_dates = [d for d in mature_dates[first:second] if end_dates[d] < holdout_dates[0]]
    selection_outputs = walk_forward(records, selection_dates)
    selection = {v: evaluate(selection_outputs, v) for v in VARIANTS}
    # Pick the variant exclusively on the middle period, before holdout runs.
    winner = max(VARIANTS, key=lambda v: (
        period_passes(selection[v][0]), number(selection[v][0].get("mean_improvement_vs_screen"))
        if number(selection[v][0].get("mean_improvement_vs_screen")) is not None else -999.))
    holdout_outputs = walk_forward(records, holdout_dates)
    holdout, holdout_cohorts = evaluate(holdout_outputs, winner)
    report = {
        "evaluation_protocol": PROTOCOL, "primary_horizon_days": HORIZON,
        "entry_policy": "next_session_close", "round_trip_cost": ROUND_TRIP_COST,
        "selection_rule": "middle_period_only", "selected_variant": winner,
        "selection": selection[winner][0], "selection_variants": {v: selection[v][0] for v in VARIANTS},
        "holdout": holdout, "holdout_cohorts": holdout_cohorts,
        "latest_feature_date": prepared["latest_date"], "features": FEATURES,
        "selection_start": selection_dates[0], "holdout_start": holdout_dates[0],
        "selection_last_exit_date": max(end_dates[d] for d in selection_dates),
        "purged_selection_weeks": second - first - len(selection_dates),
        "limitations": [
            "Historical universe and sector classifications use current S&P 500 members (survivorship bias).",
            "Historical earnings adjustments in the screen benchmark can include provider revisions; the ranker uses prices/context only.",
            "Next-session close is an execution proxy, not a guaranteed fill; costs are fixed scenarios.",
            "The p10 forecast is a statistical estimate, not a maximum-loss guarantee.",
            "Nearby weekly cohorts can overlap around holidays; uncertainty uses four-week block resampling.",
            "Repeatedly inspecting a holdout can overfit research; live frozen outcomes remain necessary.",
        ],
    }
    return report


def current_predictions(db, variant, expected_date):
    prepared = prepare(db)
    if prepared["latest_date"] != expected_date:
        raise RuntimeError("Weekly ranker feature date does not match the selection close")
    models = fit(training_before(prepared["records"], expected_date))
    latest = [r for r in prepared["records"] if r["date"] == expected_date]
    return {p["company_id"]: {**p, "rank_score": ranking_score(p["expected_excess"], p["downside_p10"], variant)}
            for p in select_predictions(predict(models, latest), variant)}
