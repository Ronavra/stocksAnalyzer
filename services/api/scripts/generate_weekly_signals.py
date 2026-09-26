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

def f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError,ValueError):
        return None

def generate(db,top=5,horizons=(5,10,20),force=False):
    rows=db.rpc("research_dashboard_candidates").execute().data or []
    if not rows:
        return []
    signal_date=max(str(r.get("price_date") or r.get("as_of_date") or "") for r in rows)
    if not force and signal_date:
        existing=(db.table("research_predictions").select("id,model_version")
                  .eq("signal_date",signal_date).limit(1).execute().data or [])
        if existing:
            print(f"Weekly cohort for {signal_date} already exists; preserving frozen selection. Use --force only for an intentional new model cohort.")
            return []

    models,model_meta=fit_models(db)
    predictions,prediction_date=predict_current(db,models) if models else ({},None)
    valid_horizons=[
        h for h,m in models.items()
        if m.diagnostics.get("calibration_beats_baseline") and m.diagnostics.get("oof_rows",0)>=1000
    ]
    print("Calibrated model valid horizons=",valid_horizons,"latest_feature_date=",prediction_date)

    ids=[r.get("company_id") for r in rows if r.get("company_id")]
    earnings={}
    if ids:
        ev=(db.table("earnings_events")
            .select("company_id,reported_date,surprise_percent,revenue_surprise_percent,source")
            .in_("company_id",ids).eq("source","massive_benzinga")
            .lte("reported_date",date.today().isoformat())
            .order("reported_date",desc=True).execute().data or [])
        for e in ev:
            earnings.setdefault(e["company_id"],e)

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
        vals=[f(e.get("surprise_percent")),f(e.get("revenue_surprise_percent"))]
        vals=[x for x in vals if x is not None]
        adj=max(-8,min(8,sum(max(-20,min(20,x)) for x in vals)/5)) if vals else 0
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
    today=date.today().isoformat()
    out=[]
    for rank,(rank_score,r,e,mp,heuristic_score,model_score,ranking_mode) in enumerate(picks[:top],1):
        for horizon in horizons:
            m=mp.get(horizon) or {}
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
                "model_version":"weekly-signal-v2-calibrated",
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
