"""Replay fixed financial weights; do not optimize weights or promote forecasts."""

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")

from app.db.client import get_supabase
from app.research.financial_ranking import load_inputs, rank_candidates, POLICY_VERSION, WEIGHTS
from app.research.weekly_rank_metrics import ROUND_TRIP_COST, tail_mean, block_lower_bound


def period_summary(cohorts):
    if not cohorts:
        return {"cohorts":0}
    net=[r["financial_return"]-(ROUND_TRIP_COST if r["financial_picks"] else 0.) for r in cohorts]
    baseline=[r["baseline_return"]-ROUND_TRIP_COST for r in cohorts]
    excess=[n-r["spy_return"] for n,r in zip(net,cohorts)]
    delta=[n-b for n,b in zip(net,baseline)]
    return {"cohorts":len(cohorts),"mean_net_return":mean(net),"baseline_mean_net_return":mean(baseline),
            "mean_excess_vs_spy":mean(excess),"mean_improvement_vs_baseline":mean(delta),
            "lower_bound_vs_baseline":block_lower_bound(delta),"worst_week":min(net),
            "worst_20pct_mean":tail_mean(net),"baseline_worst_20pct_mean":tail_mean(baseline),
            "loss_week_rate":mean(n<0 for n in net),"weeks_in_cash":sum(not c["financial_picks"] for c in cohorts)}


def compare(prepared,inputs):
    dates=sorted({r["date"] for r in prepared["records"] if r["target_excess"] is not None})
    split=int(len(dates)*.8)
    holdout_start=dates[split] if dates else None
    by_date={d:[] for d in dates}
    for r in prepared["records"]:
        if r["date"] in by_date:
            by_date[r["date"]].append(r)
    cohorts=[]; excluded=Counter(); candidate_weeks=0
    analyst_weeks=0
    for anchor,records in by_date.items():
        rows=[]; earnings={}; lookup={r["company_id"]:r for r in records}
        baseline=sorted((r for r in records if r["screen_score"] is not None),
                        key=lambda r:(-r["screen_score"],str(r["company_id"])))[:5]
        if not baseline:
            excluded["no_baseline_candidates"]+=1; continue
        for r in records:
            setup=r.get("setup") or {}
            rows.append({"company_id":r["company_id"],"current_price":r.get("selection_close"),
                         "opportunity_score":setup.get("score"),"setup_sample_size":setup.get("sample_size")})
            event=r.get("historical_earnings")
            if event:
                earnings[r["company_id"]]=event
        picks,summary=rank_candidates(rows,inputs,anchor,earnings,live=False)
        if summary.get("analyst_status",{}).get("current",0):
            analyst_weeks+=1
        if summary["ranking_eligible"]:
            candidate_weeks+=1
        chosen=[lookup[p["row"]["company_id"]] for p in picks]
        if any(r["actual_return"] is None or r["spy_return"] is None for r in baseline+chosen):
            excluded["missing_selected_outcome"]+=1; continue
        cohorts.append({"date":anchor,"financial_return":mean(r["actual_return"] for r in chosen) if chosen else 0.,
                        "baseline_return":mean(r["actual_return"] for r in baseline),"spy_return":baseline[0]["spy_return"],
                        "financial_eligible":summary["financial_eligible"],
                        "financial_picks":[p["row"]["company_id"] for p in picks]})
    return {"policy_version":POLICY_VERSION,"weights":WEIGHTS,"validated_forecast":False,
            "evaluation_protocol":"fixed_financial_analyst_next_close_5d_v2","entry_policy":"next_session_close",
            "analyst_observed_weeks":analyst_weeks,"analyst_comparison_ready":analyst_weeks>=26,
            "round_trip_cost":ROUND_TRIP_COST,"latest_price_date":prepared["latest_date"],
            "attempted_weeks":len(dates),"weeks_with_qualifying_financial_candidates":candidate_weeks,
            "excluded":dict(excluded),"holdout_start":holdout_start,
            "earlier_period":period_summary([c for c in cohorts if c["date"]<holdout_start]),
            "holdout":period_summary([c for c in cohorts if c["date"]>=holdout_start]),
            "all":period_summary(cohorts),"cohorts":cohorts,
            "limitations":[
                "Weights are the user's fixed preference, not fitted or chosen from returns.",
                "Historical SEC audit snapshots are unavailable: replay uses period age and filing-date availability only; live ranking requires latest-filing verification.",
                "Restatements/backfills overwrite historical filing rows; history can leave early weeks in cash and is not point-in-time-certified.",
                "Historical constituents/sectors use today's universe; earnings can include provider revisions.",
                "The outcome period has been inspected in prior research; the last 20% is a descriptive audit, not a new untouched test.",
                "This comparison does not approve a return forecast. Frozen forward outcomes are required.",
                "Analyst consensus requires actual capture timestamps. Backfilled monthly rows cannot be treated as known then; missing historical observations are neutral, so this replay does not establish analyst value.",
            ]}


def main():
    from app.research.weekly_ranker import prepare
    db=get_supabase()
    created=db.table("pipeline_runs").insert({"pipeline":"weekly_financial_comparison","status":"running",
        "started_at":datetime.now(timezone.utc).isoformat()}).execute().data or []
    run_id=created[0]["id"] if created else None
    try:
        report=compare(prepare(db),load_inputs(db,analyst_history=True))
        (API_DIR/"financial_ranking_comparison.json").write_text(json.dumps(report,indent=2)+"\n")
        if run_id:
            db.table("pipeline_runs").update({"status":"success","finished_at":datetime.now(timezone.utc).isoformat(),"metadata":report}).eq("id",run_id).execute()
        print(json.dumps({k:v for k,v in report.items() if k!="cohorts"},indent=2),flush=True)
    except Exception as exc:
        if run_id:
            db.table("pipeline_runs").update({"status":"error","finished_at":datetime.now(timezone.utc).isoformat(),"error_message":str(exc)[:2000]}).eq("id",run_id).execute()
        raise


if __name__=="__main__":
    main()
