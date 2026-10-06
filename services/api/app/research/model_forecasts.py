"""Publish only forecasts whose recorded chronological validation passed."""
from datetime import datetime,timezone
from .validation_gate import validated_horizons
from .model_identity import MODEL_VERSION


def publish_forecasts(db,run_id,models,validation):
    horizons=validated_horizons({**validation,"model_version":MODEL_VERSION})
    if not horizons or run_id is None:
        return {"published":0,"validated_horizons":[]}
    from .calibrated_model import predict_current
    predictions,day=predict_current(db,{h:models[h] for h in horizons if h in models})
    active={r['id'] for r in db.table('companies').select('id').eq('is_sp500',True).execute().data or []}
    observed=datetime.now(timezone.utc).isoformat(); rows=[]
    for cid,forecasts in predictions.items():
        if cid not in active:
            continue
        for h,forecast in forecasts.items():
            if forecast['feature_coverage']<.80:
                continue
            rows.append({'company_id':cid,'feature_date':day,'horizon_days':h,'model_version':MODEL_VERSION,
                         'validation_run_id':run_id,'generated_at':observed,
                         'probability_up':forecast['probability_up'],'expected_return':forecast['expected_return'],
                         'feature_coverage':forecast['feature_coverage'],'diagnostics':forecast['diagnostics']})
    for offset in range(0,len(rows),300):
        db.table('model_forecasts').upsert(rows[offset:offset+300],on_conflict='company_id,feature_date,horizon_days,model_version,validation_run_id',ignore_duplicates=True,returning='minimal').execute()
    return {'published':len(rows),'validated_horizons':list(horizons),'feature_date':day,'fixed_selection_weights_unchanged':True}
