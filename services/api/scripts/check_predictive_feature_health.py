"""Exercise observed financial features without training or promoting a model."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.research.calibrated_model import load_ttm_fundamentals, observed_fundamental_asof, MODEL_VERSION


def check(db):
    companies=db.table("companies").select("id,ticker").eq("is_sp500",True).execute().data or []
    latest=db.table("price_history").select("price_date").order("price_date",desc=True).limit(1).execute().data or []
    if not companies or not latest:
        raise RuntimeError("No current universe or market close")
    day=latest[0]["price_date"]
    snapshots=load_ttm_fundamentals(db)
    checked=available=0
    for company in companies:
        values=observed_fundamental_asof(snapshots.get(company["id"],[]),day)
        checked+=1
        available+=values.get("_ttm_eps") is not None
    return {"model_version":MODEL_VERSION,"market_date":day,"companies_checked":checked,
            "companies_with_available_observed_financials":available,
            "full_history_available":not bool(getattr(db,"history_policy",None)) or bool(getattr(db,"archive",None)),
            "validated_forecast":False,"model_promoted":False,
            "scope":"Observed financial feature runtime; not out-of-sample validation"}


def main():
    db=get_supabase()
    started=datetime.now(timezone.utc).isoformat()
    try:
        report=check(db)
        db.table("pipeline_runs").insert({"pipeline":"predictive_feature_health","status":"success",
            "started_at":started,"finished_at":datetime.now(timezone.utc).isoformat(),"metadata":report}).execute()
        (API_DIR/"predictive_feature_health.json").write_text(json.dumps(report,indent=2)+"\n")
        print(json.dumps(report),flush=True)
    except Exception as exc:
        db.table("pipeline_runs").insert({"pipeline":"predictive_feature_health","status":"error",
            "started_at":started,"finished_at":datetime.now(timezone.utc).isoformat(),"error_message":str(exc)[:2000]}).execute()
        raise


if __name__=="__main__": main()
