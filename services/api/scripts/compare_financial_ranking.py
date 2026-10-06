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
from app.research.observations import close_cutoff, member_asof, timestamp, earnings_versions
from app.research.earnings_catalysts import upcoming_from_events


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
        if inputs.get("point_in_time"):
            first=timestamp(inputs.get("first_observed_at"))
            if first is None or close_cutoff(anchor)<first:
                excluded["financial_history_not_observed"]+=1; continue
            earnings_start=timestamp(inputs.get("first_earnings_observation"))
            if earnings_start is None or close_cutoff(anchor)<earnings_start:
                excluded["earnings_history_not_observed"]+=1; continue
            records=[r for r in records if member_asof(inputs.get("memberships",[]),r["company_id"],anchor)]
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
        upcoming={}
        if inputs.get("point_in_time"):
            events=earnings_versions(inputs.get("earnings_observations",[]),close_cutoff(anchor))
            earnings={}
            for event in sorted(events,key=lambda x:x["reported_date"]):
                age=(datetime.fromisoformat(anchor)-datetime.fromisoformat(event["reported_date"])).days
                if event.get("reported_eps") is not None and 0<age<=30 and event.get("source")=="massive_benzinga":
                    earnings[event["company_id"]]=event
            upcoming=upcoming_from_events(events,anchor)
        picks,summary=rank_candidates(rows,inputs,anchor,earnings,live=False,now=close_cutoff(anchor),upcoming=upcoming)
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
            "financial_history_mode":"observed_point_in_time" if inputs.get("point_in_time") else "filing_date_proxy",
            "first_financial_observation":inputs.get("first_observed_at"),"first_earnings_observation":inputs.get("first_earnings_observation"),
            "evaluation_protocol":"fixed_financial_analyst_next_close_5d_v3_observed","entry_policy":"next_session_close",
            "analyst_observed_weeks":analyst_weeks,"analyst_comparison_ready":analyst_weeks>=26,
            "round_trip_cost":ROUND_TRIP_COST,"latest_price_date":prepared["latest_date"],
            "attempted_weeks":len(dates),"weeks_with_qualifying_financial_candidates":candidate_weeks,
            "excluded":dict(excluded),"holdout_start":holdout_start,
            "earlier_period":period_summary([c for c in cohorts if c["date"]<holdout_start]),
            "holdout":period_summary([c for c in cohorts if c["date"]>=holdout_start]),
            "all":period_summary(cohorts),"cohorts":cohorts,
            "limitations":[
                "Weights are the user's fixed preference, not fitted or chosen from returns.",
                "Strict replay uses observed financial versions and recorded constituent intervals; dates before the archive began are excluded rather than counted as cash weeks.",
                "Original pre-archive filings, event calendars and historical sector classifications are not reconstructed. Earnings and expected dates use only actually observed versions.",
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
        report=compare(prepare(db,point_in_time=True),load_inputs(db,analyst_history=True,point_in_time=True))
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
