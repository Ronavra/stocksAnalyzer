import argparse
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")

from app.db.client import get_supabase
from app.research.calibrated_model import MODEL_VERSION, fit_models, predict_current
from app.research.earnings_catalysts import catalyst_adjustment, recent_earnings
from app.research.validation_gate import validated_horizons

def f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError,ValueError):
        return None

def current_candidates(rows):
    """Use only setups calculated from the most recent market close."""
    signal_date=max((str(r.get("price_date") or "") for r in rows),default="")
    return signal_date,[r for r in rows if str(r.get("price_date") or "")==signal_date
                        and str(r.get("as_of_date") or "")==signal_date]

def validated_groups(db):
    rows=(db.table("model_validation_runs")
          .select("started_at,finished_at,best_stage,best_groups,results,model_version,status")
          .eq("model_version",MODEL_VERSION)
          .order("started_at",desc=True).limit(1).execute().data or [])
    if rows and isinstance(rows[0].get("best_groups"),list) and rows[0]["best_groups"]:
        run=rows[0]
        valid=validated_horizons(run)
        if valid:
            return tuple(run["best_groups"]),run.get("finished_at"),valid
    return ("price","context","earnings","fundamentals"),None,()

def generate(db,top=5,horizons=(5,10,20),force=False):
    rows=db.rpc("research_dashboard_candidates").execute().data or []
    if not rows:
        raise RuntimeError("No setup snapshots available; weekly cohort not published")
    signal_date,rows=current_candidates(rows)
    if not rows:
        raise RuntimeError(f"No current setup snapshots for the latest price date {signal_date}")
    if not force and signal_date:
        existing=(db.table("research_predictions").select("id,model_version")
                  .eq("signal_date",signal_date).limit(1).execute().data or [])
        if existing:
            print(f"Weekly cohort for {signal_date} already exists; preserving frozen selection. Use --force only for an intentional new model cohort.")
            return []

    groups,validated_at,validated_horizons=validated_groups(db)
    print("Validated production feature groups=",groups,"validated_at=",validated_at,"horizons=",validated_horizons)
    models,model_meta=fit_models(db,groups=groups) if validated_horizons else ({},{})
    predictions,prediction_date=predict_current(db,models) if models else ({},None)
    valid_horizons=[
        h for h,m in models.items()
        if h in validated_horizons and m.diagnostics.get("calibration_beats_baseline")
        and m.diagnostics.get("oof_rows",0)>=1000
    ]
    print("Calibrated model valid horizons=",valid_horizons,"latest_feature_date=",prediction_date)

    earnings=recent_earnings(db,rows)

    picks=[]
    for r in rows:
        score=f(r.get("opportunity_score"))
        up=f(r.get("setup_probability_up"))
        med=f(r.get("setup_median_return_5d"))
        n=int(r.get("setup_sample_size") or 0)
        price=f(r.get("current_price"))
        if None in (score,up,med,price) or n<50:
            continue
        e=earnings.get(r.get("company_id")) or {}
        adj=catalyst_adjustment(e)
        heuristic_score=score+adj
        if up<0.52 or med<=0:
            continue

        mp=predictions.get(r.get("company_id"),{})
        probs=[mp[h]["probability_up"] for h in valid_horizons if h in mp]
        # Activate model influence only when walk-forward calibration beat the
        # historical base-rate Brier score. Until then, the frozen heuristic
        # remains the production fallback.
        if len(probs)>=2:
            model_score=100*sum(probs)/len(probs)
            rank_score=.70*model_score+.30*heuristic_score
            ranking_mode="calibrated_blend"
        else:
            model_score=None
            rank_score=heuristic_score
            ranking_mode="heuristic_fallback"
        picks.append((rank_score,r,e,mp,heuristic_score,model_score,ranking_mode))

    picks.sort(key=lambda x:x[0],reverse=True)
    if not picks:
        raise RuntimeError(f"No qualifying candidates for market close {signal_date}; weekly cohort not published")
    today=date.today().isoformat()
    out=[]
    for rank,(rank_score,r,e,mp,heuristic_score,model_score,ranking_mode) in enumerate(picks[:top],1):
        for horizon in horizons:
            m=(mp.get(horizon) or {}) if horizon in valid_horizons else {}
            diag=m.get("diagnostics") or {}
            rec={
                "company_id":r["company_id"],
                "signal_date":r.get("price_date") or r.get("as_of_date") or today,
                "horizon_days":horizon,
                "signal":"UP",
                "rank":rank,
                "entry_price":r.get("current_price"),
                "research_score":round(rank_score,2),
                "historical_up_rate":r.get("setup_probability_up"),
                "historical_median_return":r.get("setup_median_return_5d"),
                "sample_size":r.get("setup_sample_size"),
                "catalyst":e or None,
                "model_version":"weekly-signal-v4-calibrated" if ranking_mode=="calibrated_blend" else "weekly-signal-v4-heuristic",
                "model_probability_up":m.get("probability_up"),
                "model_expected_return":m.get("expected_return"),
                "model_calibration_brier":diag.get("calibrated_brier"),
                "model_baseline_brier":diag.get("baseline_brier"),
                "model_feature_coverage":m.get("feature_coverage"),
                "model_diagnostics":{
                    "predictive_model":MODEL_VERSION,
                    "ranking_mode":ranking_mode,
                    "heuristic_score":round(heuristic_score,4),
                    "model_score":model_score,
                    "training":diag,
                    "model_meta":model_meta,
                    "selection_context":{
                        "upside_to_60d_high":r.get("upside_to_60d_high"),
                        "drawdown_60d":r.get("setup_drawdown_60d"),
                    },
                },
            }
            db.table("research_predictions").upsert(
                rec,on_conflict="company_id,signal_date,horizon_days,model_version"
            ).execute()
        out.append((r.get("ticker"),rank_score,r.get("current_price"),ranking_mode))
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--top",type=int,default=5)
    ap.add_argument("--horizons",nargs="+",type=int,choices=[5,10,20],default=[5,10,20])
    ap.add_argument("--force",action="store_true")
    a=ap.parse_args()
    picks=generate(get_supabase(),a.top,tuple(a.horizons),a.force)
    print(f"Saved {len(picks)} frozen candidates across horizons {a.horizons}")
    for i,(ticker,score,price,mode) in enumerate(picks,1):
        print(f"{i}. {ticker} research_score={score:.1f} entry={price} ranking={mode}")

if __name__=="__main__":
    main()
