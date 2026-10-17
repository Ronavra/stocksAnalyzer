import json
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")

from app.db.client import get_supabase
from app.research.calibrated_model import MODEL_VERSION, fit_models
from app.research.model_forecasts import publish_forecasts

BASE=("price","context")
# Independent additions keep a young guidance archive from blocking other tests.
STAGES=[("price",("price",)),("price_context",BASE)]+[
    ("base_plus_"+group,BASE+(group,))
    for group in ("earnings","fundamentals","valuation","guidance","news","estimates","analyst")
]+[("full",("price","context","earnings","fundamentals","valuation","guidance","news","estimates","analyst"))]


def stage_score(horizons):
    vals=[
        x["selection_calibrated_brier"] for x in horizons.values()
        if x.get("selection_beats_baseline") and x.get("selection_calibrated_brier") is not None
    ]
    return (sum(vals)/len(vals),len(vals)) if vals else (None,0)

def main():
    db=get_supabase()
    from app.db.market_history import require_full_history
    require_full_history(db)
    claim=db.rpc("claim_predictive_validation",{"p_model_version":MODEL_VERSION,"p_claim":True}).execute().data or {}
    if not claim.get("run"):
        print("Validation already running; preserving its lease.",flush=True)
        return
    run_id=claim["id"]
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
                    "return_mae_beats_baseline":d.get("return_mae_beats_baseline"),
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
                             for group in groups if group in ("fundamentals","valuation","earnings","guidance","news","estimates","analyst"))
            results[name]["observed_family_ready"]=family_ready
            if family_ready and n_valid>=2 and score is not None and (best_score is None or score<best_score-1e-5):
                best_stage=name; best_groups=list(groups); best_score=score
                best_models=models

        print("\nFeature value against the preregistered base, using the selection period only:")
        base=results["price_context"]["horizons"]
        for name,_ in STAGES:
            if name in ("price","price_context"):
                continue
            deltas={}
            for h,cur in results[name]["horizons"].items():
                if h in base:
                    deltas[h]=cur["selection_calibrated_brier"]-base[h]["selection_calibrated_brier"]
            results[name]["selection_delta_vs_price_context"]=deltas
            print(name,json.dumps(deltas),flush=True)

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
        from app.research.validation_gate import validated_horizons
        valid=validated_horizons({**payload,"model_version":MODEL_VERSION})
        outcome="validated" if valid else "insufficient_history" if not best_models else "baseline_not_beaten"
        results["execution"]={"outcome":outcome,"validated_horizons":list(valid),
                              "selection_weights_changed":False}
        saved=db.table("model_validation_runs").update(payload).eq("id",run_id).eq("status","running").gte("started_at",(datetime.now(timezone.utc)-timedelta(hours=6)).isoformat()).execute().data
        if not saved:
            raise RuntimeError("Validation lease expired or was superseded; results and forecasts withheld")
        forecast_report=publish_forecasts(db,run_id,best_models,payload)
        db.table("pipeline_runs").insert({"pipeline":"model_validation_execution","status":"success",
            "started_at":payload["finished_at"],"finished_at":payload["finished_at"],
            "metadata":{**results["execution"],"validation_run_id":run_id,
                        "full_history_available":True,"model_version":MODEL_VERSION}}).execute()
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
            }).eq("id",run_id).in_("status",["running","success"]).execute()
        db.table("pipeline_runs").insert({"pipeline":"model_validation_execution","status":"error",
            "started_at":datetime.now(timezone.utc).isoformat(),"finished_at":datetime.now(timezone.utc).isoformat(),
            "metadata":{"outcome":"failed","validation_run_id":run_id},"error_message":str(exc)[:500]}).execute()
        traceback.print_exc()
        raise

if __name__=="__main__":
    main()
