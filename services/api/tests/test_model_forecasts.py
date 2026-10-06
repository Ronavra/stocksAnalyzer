from app.research.model_forecasts import publish_forecasts
from app.research.model_identity import MODEL_VERSION
from app.research.validation_gate import validated_horizons


def test_failed_validation_publishes_nothing_without_contacting_database():
    assert publish_forecasts(None,1,{}, {'status':'error','model_version':MODEL_VERSION})=={'published':0,'validated_horizons':[]}


def test_sparse_new_source_families_cannot_be_promoted_despite_good_brier_scores():
    run={'status':'success','model_version':MODEL_VERSION,'best_stage':'full','results':{'full':{'observed_family_ready':False,'horizons':{}}}}
    assert validated_horizons(run)==()
