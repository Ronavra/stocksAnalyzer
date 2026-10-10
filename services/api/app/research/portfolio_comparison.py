"""Capital-constrained replay of frozen publications, independently per policy.

Adjusted closes represent reinvested total-return units, never execution quotes.
This measures an explicit paper portfolio; it does not promote a forecast.
"""
from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta
from math import ceil
from statistics import mean, stdev

from .observations import timestamp
from ..market_calendar import is_trading_day, session_close
from .price_window import canonical_prices
from .weekly_rank_metrics import number

PROTOCOL = "frozen_capital_constrained_next_close_v1"
INITIAL_CAPITAL = 10000.
COST_SCENARIOS = {"base": .002, "stress": .005}


def positive(value):
    value = number(value)
    return value if value is not None and value > 0 else None


def entry_index(cohort, calendar):
    """Never trade at a close preceding the actual publication timestamp."""
    published = timestamp(cohort.get("published_at"))
    if published is None:
        return None
    index = bisect_right(calendar, cohort["signal_date"])
    while index < len(calendar) and session_close(date.fromisoformat(calendar[index])) <= published:
        index += 1
    return index


def drawdown(values, initial=INITIAL_CAPITAL):
    peak = initial
    worst = 0.
    for value in values:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return worst


def summarize(curve):
    if not curve:
        return {}
    last = curve[-1]
    elapsed = (date.fromisoformat(last["date"]) - date.fromisoformat(curve[0]["date"])).days
    returns = [b["equity"] / a["equity"] - 1 for a, b in zip(curve, curve[1:])]
    spy_returns = [b["benchmark_equity"] / a["benchmark_equity"] - 1 for a, b in zip(curve, curve[1:])]
    excess = [a - b for a, b in zip(returns, spy_returns)]
    tracking = stdev(excess) * 252 ** .5 if len(excess) >= 60 else None
    return {
        "start_date": curve[0]["date"], "as_of_date": last["date"], "sessions": len(curve),
        "portfolio_value": last["equity"], "benchmark_value": last["benchmark_equity"],
        "cumulative_return": last["equity"] / INITIAL_CAPITAL - 1,
        "benchmark_return": last["benchmark_equity"] / INITIAL_CAPITAL - 1,
        "excess_return": (last["equity"] - last["benchmark_equity"]) / INITIAL_CAPITAL,
        "max_drawdown": drawdown([p["equity"] for p in curve]),
        "benchmark_max_drawdown": drawdown([p["benchmark_equity"] for p in curve]),
        "annualized_return": (last["equity"] / INITIAL_CAPITAL) ** (365.25 / elapsed) - 1 if elapsed >= 365 else None,
        "tracking_error": tracking,
        "information_ratio": mean(excess) * 252 / tracking if tracking else None,
        "cash_fraction": last["cash"] / last["equity"],
    }


def simulate(cohorts, predictions, prices, calendar, benchmark_id, horizon, round_trip_cost=.002):
    """Rotate ceil(horizon/5) funded sleeves; busy sleeves cannot borrow capital.

Each sleeve starts with an equal share of the initial capital and reinvests its
own proceeds. Exits precede entries at the same close. No-pick groups stay cash;
off-schedule groups with no free sleeve are recorded as unfunded, never leveraged.
"""
    if horizon not in (5, 10, 20) or not 0 <= round_trip_cost < 1:
        raise ValueError("Unsupported horizon or transaction cost")
    calendar = sorted(set(calendar))
    maps = defaultdict(dict)
    for row in canonical_prices(prices):
        maps[row["company_id"]][row["price_date"]] = positive(row.get("close"))
    events = defaultdict(list)
    issues = []
    pending = 0
    for cohort in sorted(cohorts, key=lambda c: (c["signal_date"], c.get("published_at") or "")):
        if cohort.get("status") != "published" or horizon not in cohort["horizons"]:
            continue
        index = entry_index(cohort, calendar)
        if index is None:
            issues.append({"reason": "publication_time_missing", "signal_date": cohort["signal_date"]})
            continue
        if index >= len(calendar):
            pending += 1
            continue
        rows = [p for p in predictions if p["signal_date"] == cohort["signal_date"]
                and p["model_version"] == cohort["model_version"] and p["horizon_days"] == horizon]
        events[index].append((cohort, rows))
    if issues or not events:
        return {"status": "blocked" if issues else "pending", "issues": issues,
                "pending_cohorts": pending, "curve": [], "summary": {}, "validated_forecast": False}
    start = min(events)
    count = ceil(horizon / 5)
    sleeves = [{"cash": INITIAL_CAPITAL / count, "positions": {}, "exit": None} for _ in range(count)]
    side_cost = round_trip_cost / 2
    curve = []
    benchmark_units = None
    costs = traded = 0.
    funded = completed = cash_groups = 0
    unfunded = []
    for index in range(start, len(calendar)):
        day = calendar[index]
        spy = maps[benchmark_id].get(day)
        held = {cid for sleeve in sleeves for cid in sleeve["positions"]}
        missing = [cid for cid in held if maps[cid].get(day) is None]
        if spy is None or missing:
            issues.append({"reason": "missing_exact_session_price", "date": day,
                           "company_ids": sorted(missing + ([benchmark_id] if spy is None else []))})
            break
        # Validate funded entries before mutating this day's account.
        free_count = sum(s["exit"] is None or s["exit"] <= index for s in sleeves)
        valid = True
        for cohort, rows in events.get(index, []):
            if free_count == 0:
                continue
            free_count -= 1
            expected = cohort["expected_picks"]
            if len(rows) != expected or len({p["company_id"] for p in rows}) != expected:
                issues.append({"reason": "incomplete_frozen_cohort", "date": day, "signal_date": cohort["signal_date"]})
                valid = False
                break
            missing_entry = [p["company_id"] for p in rows if maps[p["company_id"]].get(day) is None]
            if missing_entry:
                issues.append({"reason": "missing_entry_price", "date": day, "company_ids": missing_entry})
                valid = False
                break
        if not valid:
            break
        if benchmark_units is None:
            benchmark_units = INITIAL_CAPITAL / (spy * (1 + side_cost))
        for sleeve in sleeves:
            if sleeve["exit"] is not None and sleeve["exit"] <= index:
                proceeds = sum(units * maps[cid][day] for cid, units in sleeve["positions"].items())
                fee = proceeds * side_cost
                sleeve["cash"] += proceeds - fee
                costs += fee
                traded += proceeds
                sleeve.update(positions={}, exit=None)
                completed += 1
        for cohort, rows in events.get(index, []):
            sleeve = next((s for s in sleeves if s["exit"] is None), None)
            if sleeve is None:
                unfunded.append({"signal_date": cohort["signal_date"], "entry_date": day, "reason": "capital_committed"})
                continue
            funded += 1
            sleeve["exit"] = index + horizon
            if not rows:
                cash_groups += 1
                continue
            allocation = sleeve["cash"] / len(rows)
            for row in rows:
                notional = allocation / (1 + side_cost)
                fee = allocation - notional
                sleeve["positions"][row["company_id"]] = notional / maps[row["company_id"]][day]
                costs += fee
                traded += notional
            sleeve["cash"] = 0.
        cash = sum(s["cash"] for s in sleeves)
        positions = sum(units * maps[cid][day] for s in sleeves for cid, units in s["positions"].items())
        curve.append({"date": day, "equity": cash + positions, "benchmark_equity": benchmark_units * spy,
                      "cash": cash, "invested": positions, "trading_costs": costs})
    summary = summarize(curve)
    summary.update(trading_costs=costs, traded_notional=traded, turnover_on_initial_capital=traded / INITIAL_CAPITAL,
                   funded_cohorts=funded, completed_cohorts=completed, cash_cohorts=cash_groups,
                   unfunded_cohorts=len(unfunded), open_cohorts=funded - completed)
    return {"status": "blocked" if issues else "ok", "issues": issues, "pending_cohorts": pending,
            "unfunded": unfunded, "sleeves": count, "round_trip_cost": round_trip_cost,
            "summary": summary, "curve": curve, "validated_forecast": False}


def compare_portfolios(cohorts, predictions, price_rows, total_return_rows, benchmark_id, active_version):
    observed = sorted({r["price_date"] for r in price_rows if r["company_id"] == benchmark_id and positive(r.get("close"))})
    calendar=[]
    if observed:
        first_signal=min((c["signal_date"] for c in cohorts if c.get("status")=="published"),default=observed[0])
        # A pruned/missing leading SPY history must not move old entries to the
        # first downloaded bar. Expected sessions start at the frozen signals.
        day=date.fromisoformat(min(first_signal,observed[0])); end=date.fromisoformat(observed[-1])
        while day<=end:
            if is_trading_day(day):
                calendar.append(day.isoformat())
            day+=timedelta(days=1)
    policies = {}
    for version in sorted({c["model_version"] for c in cohorts} | {active_version}):
        groups = [c for c in cohorts if c["model_version"] == version]
        policies[version] = {}
        for horizon in (5, 10, 20):
            policies[version][str(horizon)] = {
                basis: {scenario: simulate(groups, predictions, rows, calendar, benchmark_id, horizon, cost)
                        for scenario, cost in COST_SCENARIOS.items()}
                for basis, rows in (("price_return", price_rows), ("total_return", total_return_rows))
            }
    return {"protocol": PROTOCOL, "initial_capital": INITIAL_CAPITAL, "currency": "USD",
            "active_version": active_version, "by_policy": policies, "validated_forecast": False,
            "rules": {"entry": "first_close_after_signal_and_publication", "sizing": "equal_weight_rotating_sleeves",
                      "sleeves": "ceil(horizon_days/5)", "unfunded": "skip_without_leverage",
                      "idle_capital": "cash_zero_yield", "benchmark": "SPY_buy_and_hold_same_dates",
                      "costs": "half_round_trip_at_each_buy_and_sell; benchmark_pays_entry",
                      "valuation": "mark_to_market_without_hypothetical_final_liquidation",
                      "total_return": "provider_split_and_dividend_adjusted_close; dividends_reinvested",
                      "taxes": "excluded", "annualization": "only_after_365_calendar_days"}}


def load_portfolio_comparison(db):
    from .prospective_metrics import paged
    from .financial_ranking import SIGNAL_VERSION
    from ..market_calendar import latest_completed_session

    cohorts=paged(db.table("recommendation_cohorts").select("*").order("signal_date"))
    predictions=paged(db.table("research_predictions")
                      .select("company_id,signal_date,horizon_days,model_version").order("id"))
    companies=db.table("companies").select("id,ticker").order("id").execute().data or []
    spy=next((c for c in companies if c["ticker"]=="SPY"),None)
    if not spy:
        return {"status":"unavailable","reason":"SPY benchmark is missing","by_policy":{}}
    ids=sorted({p["company_id"] for p in predictions}|{spy["id"]})
    start=min((c["signal_date"] for c in cohorts),default=latest_completed_session().isoformat())
    prices=paged(db.table("price_history").select("company_id,price_date,close,source").in_("company_id",ids)
                 .gte("price_date",start).order("price_date").order("company_id").order("source"))
    adjusted=[]
    source_error=None
    try:
        series=paged(db.table("portfolio_return_series").select("company_id,source,adjustment,observed_at,bars")
                     .in_("company_id",ids).order("company_id"))
        for row in series:
            if row["source"]=="twelvedata_adjust_all" and row["adjustment"]=="all":
                adjusted.extend({**bar,"company_id":row["company_id"],"source":row["source"]} for bar in row["bars"])
    except Exception:
        # A missing/unavailable evaluation source cannot take down the price
        # comparison or turn price-only returns into a total-return claim.
        source_error="Total-return data could not be loaded"
    result=compare_portfolios(cohorts,predictions,prices,adjusted,spy["id"],SIGNAL_VERSION)
    result["tickers"]={str(c["id"]):c["ticker"] for c in companies if c["id"] in ids}
    result["total_return_source_error"]=source_error
    result["latest_market_date"]=max((p["price_date"] for p in prices if p["company_id"]==spy["id"]),default=None)
    result["expected_market_date"]=latest_completed_session().isoformat()
    result["market_current"]=result["latest_market_date"]==result["expected_market_date"]
    return result
