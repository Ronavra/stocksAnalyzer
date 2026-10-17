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
from app.research.recommendation_cadence import publication_due
import json

def current_candidates(rows):
    """Use only setups calculated from the most recent market close."""
    signal_date=max((str(r.get("price_date") or "") for r in rows),default="")
    return signal_date,[r for r in rows if str(r.get("price_date") or "")==signal_date
                        and str(r.get("as_of_date") or "")==signal_date]

def generate(db,top=5,horizons=(5,10,20),force=False,dry_run=False,replace_week=None,reason=None):
    if not 1<=top<=5:
        raise ValueError("Weekly shortlist size must be between one and five")
    rows=db.rpc("research_dashboard_candidates").execute().data or []
    if not rows:
        raise RuntimeError("No setup snapshots available; weekly cohort not published")
    signal_date,rows=current_candidates(rows)
    if not rows:
        raise RuntimeError(f"No current setup snapshots for the latest price date {signal_date}")
    existing=None
    if replace_week:
        if replace_week!=signal_date:
            raise RuntimeError("Replacement must match the latest market/setup date")
        if not reason or len(reason.strip())<10:
            raise ValueError("Replacement requires a documented reason")
        cohorts=db.table("recommendation_cohorts").select("model_version,published_at").eq("signal_date",signal_date).limit(1).execute().data or []
        if not cohorts:
            raise RuntimeError("No existing weekly cohort to replace")
        existing=cohorts[0]
    if not dry_run and not replace_week and not publication_due(db,signal_date):
        return []
    earnings=recent_earnings(db,rows)
    upcoming=upcoming_earnings(db,rows,signal_date)
    inputs=load_inputs(db,signal_date)
    picks,summary=rank_candidates(rows,inputs,signal_date,earnings,top=top,upcoming=upcoming)
    risk_rows=db.table("price_features").select("company_id,volatility_20d").in_("company_id",[p["row"]["company_id"] for p in picks]).eq("feature_date",signal_date).execute().data if picks else []
    risk_volatility={r["company_id"]:r.get("volatility_20d") for r in risk_rows or []}
    report={**summary,"dry_run":dry_run,"picks":[{
        "ticker":p["row"].get("ticker"),"company_id":p["row"]["company_id"],
        "score":p["score"],"financial":p["financial"],"contributions":p["contributions"],
        "technical_score":p["technical_score"],"earnings_score":p["earnings_score"],
        "analyst":p["analyst"],"earnings_available":p["earnings_available"],
        "earnings_availability_reason":"recent_surprise" if p["earnings_available"] else "recent_report_without_surprise" if p["catalyst"] else "no_report_in_30_days",
    } for p in picks]}
    (API_DIR/"financial_selection.json").write_text(json.dumps(report,indent=2)+"\n")
    print("Financial weekly selection:",json.dumps(summary),flush=True)
    out=[]
    records=[]
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
            "selection_context":{"sector":inputs["companies"][row["company_id"]].get("sector"),
                                 "volatility_20d":risk_volatility.get(row["company_id"]),"observed_at":summary["decision_at"],
                                 "upside_to_60d_high":row.get("upside_to_60d_high"),"drawdown_60d":row.get("setup_drawdown_60d")},
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
        if replace_week and not records:
            raise RuntimeError("Empty replacement refused; existing publication preserved")
        params={
            "p_signal_date":signal_date,"p_model_version":SIGNAL_VERSION,
            "p_horizons":list(horizons),"p_predictions":records,"p_metadata":report,
        }
        if existing:
            params.update(p_expected_version=existing["model_version"],
                          p_expected_published_at=existing["published_at"],p_reason=reason)
        result=db.rpc("replace_recommendation_cohort" if existing else "publish_recommendation_cohort",params).execute().data
        if isinstance(result,dict) and result.get("status") in ("already_published","not_due"):
            print("Another run advanced the publication clock; preserving its selection:",json.dumps(result))
            return []
        if not isinstance(result,dict) or result.get("status")!=("replaced" if existing else "published"):
            raise RuntimeError(f"Recommendation publication blocked: {result}")
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--top",type=int,default=5)
    ap.add_argument("--horizons",nargs="+",type=int,choices=[5,10,20],default=[5,10,20])
    ap.add_argument("--force",action="store_true",help="Deprecated: completed cohorts always stay frozen; use --dry-run for a fresh preview")
    ap.add_argument("--dry-run",action="store_true",help="Calculate the new shortlist without writing predictions")
    ap.add_argument("--replace-week",help="Explicitly replace the latest unstarted cohort for this YYYY-MM-DD market close")
    ap.add_argument("--reason",help="Audit reason for the replacement")
    a=ap.parse_args()
    picks=generate(get_supabase(),a.top,tuple(a.horizons),a.force,a.dry_run,a.replace_week,a.reason)
    print(f"{'Previewed' if a.dry_run else 'Saved'} {len(picks)} candidates across horizons {a.horizons}")
    for i,(ticker,score,price,mode) in enumerate(picks,1):
        print(f"{i}. {ticker} research_score={score:.1f} entry={price} ranking={mode}")

if __name__=="__main__":
    main()
