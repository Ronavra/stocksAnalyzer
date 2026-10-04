import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")

from app.db.client import get_supabase
from app.research.earnings_catalysts import recent_earnings, upcoming_earnings
from app.research.weekly_rank_metrics import ROUND_TRIP_COST
from app.research.financial_ranking import load_inputs, rank_candidates, SIGNAL_VERSION
import json

def current_candidates(rows):
    """Use only setups calculated from the most recent market close."""
    signal_date=max((str(r.get("price_date") or "") for r in rows),default="")
    return signal_date,[r for r in rows if str(r.get("price_date") or "")==signal_date
                        and str(r.get("as_of_date") or "")==signal_date]

def generate(db,top=5,horizons=(5,10,20),force=False,dry_run=False):
    if not 1<=top<=5:
        raise ValueError("Weekly shortlist size must be between one and five")
    rows=db.rpc("research_dashboard_candidates").execute().data or []
    if not rows:
        raise RuntimeError("No setup snapshots available; weekly cohort not published")
    signal_date,rows=current_candidates(rows)
    if not rows:
        raise RuntimeError(f"No current setup snapshots for the latest price date {signal_date}")
    if not dry_run:
        existing=(db.table("recommendation_cohorts").select("signal_date,model_version,status")
                  .eq("signal_date",signal_date).limit(1).execute().data or [])
        if existing:
            print(f"Weekly cohort for {signal_date} already exists; preserving frozen selection.")
            return []
    earnings=recent_earnings(db,rows)
    picks,summary=rank_candidates(rows,load_inputs(db,signal_date),signal_date,earnings,top=top)
    report={**summary,"dry_run":dry_run,"picks":[{
        "ticker":p["row"].get("ticker"),"company_id":p["row"]["company_id"],
        "score":p["score"],"financial":p["financial"],"contributions":p["contributions"],
        "technical_score":p["technical_score"],"earnings_score":p["earnings_score"],
        "analyst":p["analyst"],
    } for p in picks]}
    (API_DIR/"financial_selection.json").write_text(json.dumps(report,indent=2)+"\n")
    print("Financial weekly selection:",json.dumps(summary),flush=True)
    out=[]
    records=[]
    upcoming=upcoming_earnings(db,rows,signal_date)
    for rank,p in enumerate(picks,1):
        row=p["row"]
        diagnostics={
            "ranking_mode":"financial_priority","predictive_model":None,
            "validated_forecast":False,"primary_horizon_days":5,
            "entry_policy":"next_session_close","round_trip_cost":ROUND_TRIP_COST,
            "selection_close":row.get("current_price"),
            "decision_at":summary["decision_at"],
            "financial_ranking":{"policy_version":summary["policy_version"],"weights":summary["weights"],
                **p["financial"],"technical_score":p["technical_score"],"earnings_score":p["earnings_score"],
                "earnings_available":p["earnings_available"],"contributions":p["contributions"]},
            "analyst_consensus":p["analyst"],
            "upcoming_earnings":upcoming.get(row["company_id"]),
            "selection_context":{"upside_to_60d_high":row.get("upside_to_60d_high"),"drawdown_60d":row.get("setup_drawdown_60d")},
        }
        for horizon in horizons:
            rec={"company_id":row["company_id"],"signal_date":signal_date,"horizon_days":horizon,
                 "signal":"UP","rank":rank,"entry_price":None,"research_score":p["score"],
                 "historical_up_rate":row.get("setup_probability_up"),"historical_median_return":row.get("setup_median_return_5d"),
                 "sample_size":row.get("setup_sample_size"),"catalyst":p["catalyst"] or None,
                 "model_version":SIGNAL_VERSION,"model_probability_up":None,"model_expected_return":None,
                 "model_calibration_brier":None,"model_baseline_brier":None,
                 "model_feature_coverage":p["financial"]["coverage"],"model_diagnostics":diagnostics}
            records.append(rec)
        out.append((row.get("ticker"),p["score"],row.get("current_price"),"financial_priority"))
    if not dry_run:
        result=db.rpc("publish_recommendation_cohort",{
            "p_signal_date":signal_date,"p_model_version":SIGNAL_VERSION,
            "p_horizons":list(horizons),"p_predictions":records,"p_metadata":report,
        }).execute().data
        if result and result.get("status")=="already_published":
            print("Another run published this cohort; preserving its selection.")
            return []
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--top",type=int,default=5)
    ap.add_argument("--horizons",nargs="+",type=int,choices=[5,10,20],default=[5,10,20])
    ap.add_argument("--force",action="store_true",help="Deprecated: completed cohorts always stay frozen; use --dry-run for a fresh preview")
    ap.add_argument("--dry-run",action="store_true",help="Calculate the new shortlist without writing predictions")
    a=ap.parse_args()
    picks=generate(get_supabase(),a.top,tuple(a.horizons),a.force,a.dry_run)
    print(f"{'Previewed' if a.dry_run else 'Saved'} {len(picks)} candidates across horizons {a.horizons}")
    for i,(ticker,score,price,mode) in enumerate(picks,1):
        print(f"{i}. {ticker} research_score={score:.1f} entry={price} ranking={mode}")

if __name__=="__main__":
    main()
