import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")

from app.db.client import get_supabase
from app.research.calibrated_model import MODEL_VERSION, fit_models
from app.research.model_forecasts import publish_forecasts

STAGES=[
    ("price",("price",)),
    ("price_context",("price","context")),
    ("price_context_earnings",("price","context","earnings")),
    ("price_context_earnings_fundamentals",("price","context","earnings","fundamentals")),
    ("price_context_earnings_fundamentals_valuation",("price","context","earnings","fundamentals","valuation")),
    ("with_guidance",("price","context","earnings","fundamentals","valuation","guidance")),
    ("full",("price","context","earnings","fundamentals","valuation","guidance","news")),
]

def stage_score(horizons):
    vals=[
        x["selection_calibrated_brier"] for x in horizons.values()
        if x.get("selection_beats_baseline") and x.get("selection_calibrated_brier") is not None
    ]
    return (sum(vals)/len(vals),len(vals)) if vals else (None,0)

def main():
    db=get_supabase()
    now=datetime.now(timezone.utc).isoformat()
    db.table("model_validation_runs").update({
        "status":"error","finished_at":now,
        "error_message":"Superseded by a newer model validation run"
    }).eq("model_version",MODEL_VERSION).eq("status","running").execute()
    created=(db.table("model_validation_runs").insert({
        "status":"running","model_version":MODEL_VERSION
    }).execute().data or [])
    run_id=created[0]["id"] if created else None
    results={}
    try:
        best_stage=None; best_groups=None; best_score=None
        best_models={}; price_models={}
        for name,groups in STAGES:
            models,meta=fit_models(db,groups=groups)
            if name=="price":
                price_models=models
            results[name]={"groups":list(groups),"meta":meta,"horizons":{}}
            for h,m in sorted(models.items()):
                d=m.diagnostics
                results[name]["horizons"][str(h)]={
                    "calibrated_brier":d.get("calibrated_brier"),
                    "baseline_brier":d.get("baseline_brier"),
                    "brier_skill":d.get("brier_skill"),
                    "beats_baseline":d.get("calibration_beats_baseline"),
                    "oof_rows":d.get("oof_rows"),
                    "selection_calibrated_brier":d.get("selection_calibrated_brier"),
                    "selection_baseline_brier":d.get("selection_baseline_brier"),
                    "selection_beats_baseline":d.get("selection_beats_baseline"),
                    "evaluation_protocol":d.get("evaluation_protocol"),
                    "return_holdout_mae":d.get("return_holdout_mae"),
                    "return_baseline_mae":d.get("return_baseline_mae"),
                }
                print(
                    f"{name:38} {h:2d}d "
                    f"brier={d['calibrated_brier']:.5f} baseline={d['baseline_brier']:.5f} "
                    f"skill={d.get('brier_skill'):+.2%} oof={d['oof_rows']}"
                )
            score,n_valid=stage_score(results[name]["horizons"])
            results[name]["mean_valid_brier"]=score
            results[name]["valid_horizons"]=n_valid
            # Choose the feature family using the middle period only. The
            # latest holdout is reserved for the independent promotion gate.
            family_ready=all(meta.get("observed_family_dates",{}).get(group,0)>=26
                             and meta.get("observed_training_family_dates",{}).get(group,0)>=26
                             for group in groups if group in ("fundamentals","valuation","earnings","guidance","news"))
            results[name]["observed_family_ready"]=family_ready
            if family_ready and n_valid>=2 and score is not None and (best_score is None or score<best_score-1e-5):
                best_stage=name; best_groups=list(groups); best_score=score
                best_models=models

        print("\nIncremental feature value (negative delta is better):")
        prior=None
        for name,_ in STAGES:
            cur=results[name]["horizons"]
            if prior:
                for h in ("5","10","20"):
                    if h in cur and h in prior:
                        delta=cur[h]["calibrated_brier"]-prior[h]["calibrated_brier"]
                        print(f"{name:38} {h}d delta_brier={delta:+.6f}")
            prior=cur

        if best_stage is None:
            best_stage="price"
            best_groups=["price"]
            best_models=price_models
        holdout_valid=sum(
            bool(x.get("beats_baseline") and x.get("oof_rows",0)>=1000)
            for x in results[best_stage]["horizons"].values()
        )
        payload={
            "finished_at":datetime.now(timezone.utc).isoformat(),
            "status":"success",
            "best_stage":best_stage,
            "best_groups":best_groups,
            "results":results,
        }
        if run_id:
            db.table("model_validation_runs").update(payload).eq("id",run_id).execute()
        forecast_report=publish_forecasts(db,run_id,best_models,payload)
        print("Observed learning-model forecasts:",json.dumps(forecast_report),flush=True)

        out=API_DIR/"ablation_results.json"
        out.write_text(json.dumps({
            "model_version":MODEL_VERSION,
            "best_stage":best_stage,
            "best_groups":best_groups,
            "results":results,
        },indent=2,default=str),encoding="utf-8")
        print(f"\nSelected groups={best_groups} stage={best_stage} selection_brier={best_score} holdout_valid_horizons={holdout_valid}")
        print(f"Saved {out}")
    except Exception as exc:
        if run_id:
            db.table("model_validation_runs").update({
                "finished_at":datetime.now(timezone.utc).isoformat(),
                "status":"error","error_message":str(exc)[:2000],
            }).eq("id",run_id).execute()
        traceback.print_exc()
        raise

if __name__=="__main__":
    main()
