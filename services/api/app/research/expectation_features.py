"""Fiscal-target-matched changes from real captures, never retrospective trends."""
from datetime import timedelta
from math import isfinite
from .observations import available, close_cutoff, timestamp
from .analyst_consensus import consensus_score

ESTIMATE_FEATURES=["estimate_eps_revision_7d","estimate_eps_revision_30d",
                   "estimate_revenue_revision_7d","estimate_revenue_revision_30d",
                   "estimate_eps_analysts","estimate_revenue_analysts"]
ANALYST_FEATURES=["analyst_score","analyst_buy_share","analyst_count","analyst_score_change_30d"]


def number(value):
    try:
        value=float(value)
        return value if isfinite(value) else None
    except (TypeError,ValueError): return None


def revision(current, previous):
    a,b=number(current),number(previous)
    return max(-2.,min(2.,(a-b)/abs(b))) if a is not None and b not in (None,0) else None


def estimate_asof(rows, asof):
    result={k:None for k in ESTIMATE_FEATURES};cutoff=close_cutoff(asof)
    usable=[r for r in rows if available(r,cutoff,observed_key="captured_at") and r.get("fiscal_period_end")]
    if not usable: return result
    newest=max(timestamp(r["captured_at"]) for r in usable)
    if cutoff-newest>timedelta(days=7): return result
    # The current 0q can end before today while its report is still pending.
    # Old targets that disappeared from the latest capture must not be revived.
    targets=[r for r in usable if timestamp(r["captured_at"]).date()==newest.date()]
    target=min(targets,key=lambda r:(r.get("relative_period")!="0q",
        r.get("period_type") not in ("quarter","quarterly"),r["fiscal_period_end"]))
    same=[r for r in usable if all(r.get(k)==target.get(k) for k in ("source","fiscal_period_end","period_type"))]
    current=max(same,key=lambda r:r["captured_at"])
    if cutoff-timestamp(current["captured_at"])>timedelta(days=7): return result
    result.update(estimate_eps_analysts=number(current.get("eps_analyst_count")),
                  estimate_revenue_analysts=number(current.get("revenue_analyst_count")))
    for days in (7,30):
        prior=[r for r in same if timestamp(r["captured_at"])<=cutoff-timedelta(days=days)]
        if not prior: continue
        previous=max(prior,key=lambda r:r["captured_at"])
        # A very old snapshot is not a seven-day revision.
        if cutoff-timestamp(previous["captured_at"])>timedelta(days=days+7): continue
        for metric in ("eps","revenue"):
            currency=current.get(metric+"_currency")
            if not currency or currency!=previous.get(metric+"_currency"): continue
            if metric=="eps" and (current.get("eps_basis") not in ("gaap","adjusted","non-gaap")
                                  or current["eps_basis"]!=previous.get("eps_basis")): continue
            result[f"estimate_{metric}_revision_{days}d"]=revision(current.get(metric+"_consensus"),previous.get(metric+"_consensus"))
    return result


def analyst_asof(rows, asof):
    result={k:None for k in ANALYST_FEATURES}
    current=consensus_score(rows,asof,live=False)
    if not current["available"]: return result
    result.update(analyst_score=current["score"],analyst_buy_share=current["buy_share"],analyst_count=current["analyst_count"])
    earlier=(close_cutoff(asof)-timedelta(days=30)).date().isoformat()
    previous=consensus_score(rows,earlier,live=False)
    if previous["available"]: result["analyst_score_change_30d"]=current["score"]-previous["score"]
    return result


def load_observations(db, table, observed_column):
    if db is None: return {}
    grouped={};start=0
    while True:
        rows=db.table(table).select("*").order("company_id").order(observed_column).range(start,start+999).execute().data or []
        for row in rows: grouped.setdefault(row["company_id"],[]).append(row)
        if len(rows)<1000: return grouped
        start+=1000
