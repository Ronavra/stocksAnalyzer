"""Historical replay of the production setup score and weekly filters."""

from collections import defaultdict
from datetime import date
from statistics import mean, median

from app.research.earnings_catalysts import MAX_CATALYST_AGE_DAYS, catalyst_adjustment

HORIZONS = (5, 10, 20)


def setup_at(rows, index):
    """Recompute scan_setups.py using only fully matured 5-day labels."""
    current = rows[index]
    dd = current.get("drawdown_60d")
    support = current.get("distance_to_support_60d")
    if dd is None or support is None:
        return None
    # At index i the label at i-5 has just matured. Keep the same 750-row
    # window as the live daily scan, including the current feature row.
    history = rows[max(0, index - 749):index - 4]
    returns = [float(r["forward_return_5d"]) for r in history
               if r.get("forward_return_5d") is not None
               and r.get("drawdown_60d") is not None
               and r.get("distance_to_support_60d") is not None
               and abs(float(r["drawdown_60d"]) - float(dd)) <= .04
               and abs(float(r["distance_to_support_60d"]) - float(support)) <= .04]
    count = len(returns)
    if not count:
        return None
    up = sum(x > 0 for x in returns) / count
    med = median(returns)
    upside = float(current.get("rebound_potential_60d") or 0)
    shrunk = (sum(x > 0 for x in returns) + 10) / (count + 20)
    prob = max(0, min(1, (shrunk - .45) / .25))
    ret = max(0, min(1, (med + .01) / .05))
    room = max(0, min(1, upside / .20))
    score = 100 * (.50 * prob + .30 * ret + .20 * room) * (.65 + .35 * min(1, count / 100))
    return {"score": round(score, 2), "up": up, "median": med, "sample_size": count}


def last_trading_day_of_weeks(spy_rows, start_date):
    weeks = {}
    for r in spy_rows:
        d = r["feature_date"]
        if d >= start_date:
            iso = date.fromisoformat(d).isocalendar()
            weeks[(iso.year, iso.week)] = d
    return sorted(weeks.values())


def historical_catalyst(events, signal_date):
    for e in reversed(events):
        age = (date.fromisoformat(signal_date) - date.fromisoformat(e["reported_date"])).days
        if 0 < age <= MAX_CATALYST_AGE_DAYS:
            return e
        if age > MAX_CATALYST_AGE_DAYS:
            break
    return None


def replay(price_by_company, earnings_by_company, spy_id, start_date):
    spy_rows = price_by_company[spy_id]
    anchors = last_trading_day_of_weeks(spy_rows, start_date)
    lookup = {cid: {r["feature_date"]: i for i, r in enumerate(rows)}
              for cid, rows in price_by_company.items()}
    by_week = []
    for anchor in anchors:
        if anchor not in lookup[spy_id]:
            continue
        spy = spy_rows[lookup[spy_id][anchor]]
        eligible = []
        for cid, rows in price_by_company.items():
            if cid == spy_id or anchor not in lookup[cid]:
                continue
            i = lookup[cid][anchor]
            setup = setup_at(rows, i)
            if (not setup or setup["sample_size"] < 50 or
                    setup["up"] < .52 or setup["median"] <= 0 or
                    rows[i].get("close") is None):
                continue
            event = historical_catalyst(earnings_by_company.get(cid, []), anchor)
            eligible.append({"company_id": cid,
                             "score": setup["score"],
                             "adjusted_score": setup["score"] + catalyst_adjustment(event),
                             "row": rows[i]})
        if len(eligible) < 5:
            continue
        base = sorted(eligible, key=lambda x: (-x["score"], x["company_id"]))[:5]
        adjusted = sorted(eligible, key=lambda x: (-x["adjusted_score"], x["company_id"]))[:5]
        by_week.append({"date": anchor, "spy": spy, "eligible": eligible,
                        "setup_only": base, "recent_earnings": adjusted})
    return by_week


def summarize(weeks):
    result = {"weeks_with_five_candidates": len(weeks),
              "weeks_with_changed_selection": sum(
                  {p["company_id"] for p in w["setup_only"]} !=
                  {p["company_id"] for p in w["recent_earnings"]} for w in weeks),
              "horizons": {}}
    for h in HORIZONS:
        key = f"forward_return_{h}d"
        records = defaultdict(list)
        for week in weeks:
            spy = week["spy"].get(key)
            if spy is None:
                continue
            # Compare variants on exactly the same matured cohorts. A missing
            # outcome for any selected stock cannot silently favour one variant.
            if any(p["row"].get(key) is None for variant in ("setup_only", "recent_earnings")
                   for p in week[variant]):
                continue
            for variant in ("setup_only", "recent_earnings"):
                picks = week[variant]
                actuals = [float(p["row"][key]) for p in picks]
                baseline = [float(p["row"][key]) for p in week["eligible"]
                            if p["row"].get(key) is not None]
                records[variant].append({"date": week["date"],
                                         "return": mean(actuals), "spy": float(spy),
                                         "eligible": mean(baseline),
                                         "positive_picks": sum(x > 0 for x in actuals)})
        result["horizons"][str(h)] = {}
        for variant in ("setup_only", "recent_earnings"):
            rows = records[variant]
            result["horizons"][str(h)][variant] = {
                "cohorts": len(rows), "picks": len(rows) * 5,
                "mean_portfolio_return": mean(r["return"] for r in rows),
                "mean_spy_return": mean(r["spy"] for r in rows),
                "mean_excess_vs_spy": mean(r["return"] - r["spy"] for r in rows),
                "beat_spy_week_rate": mean(r["return"] > r["spy"] for r in rows),
                "positive_pick_rate": sum(r["positive_picks"] for r in rows) / (5 * len(rows)),
                "mean_excess_vs_eligible": mean(r["return"] - r["eligible"] for r in rows),
            } if rows else {"cohorts": 0}
        base = records["setup_only"]
        adjusted = records["recent_earnings"]
        result["horizons"][str(h)]["paired_earnings_minus_setup"] = (
            mean(a["return"] - b["return"] for a, b in zip(adjusted, base))
            if base else None)
    return result
