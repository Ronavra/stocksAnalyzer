from app.research.model_identity import HORIZONS, MODEL_VERSION


def validated_horizons(run):
    if not run or run.get("status")!="success" or run.get("model_version")!=MODEL_VERSION:
        return ()
    stage=(run.get("results") or {}).get(run.get("best_stage")) or {}
    horizons=stage.get("horizons") or {}
    valid=[]
    for h in HORIZONS:
        d=horizons.get(str(h)) or {}
        cb=d.get("calibrated_brier"); bb=d.get("baseline_brier")
        scb=d.get("selection_calibrated_brier"); sbb=d.get("selection_baseline_brier")
        if (d.get("evaluation_protocol")=="chronological_calibration_selection_holdout_v4"
                and d.get("selection_beats_baseline") and scb is not None and sbb is not None and scb<sbb
                and d.get("beats_baseline") and d.get("oof_rows",0)>=1000
                and cb is not None and bb is not None and cb<bb):
            valid.append(h)
    return tuple(valid) if len(valid)>=2 else ()
