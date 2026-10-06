import subprocess, sys, traceback, time, os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

HERE=Path(__file__).resolve().parent
API_DIR=HERE.parent
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from validate_daily_cycle import validate

PY=sys.executable

def run(name,*args):
    print(f"\n=== {name} ===",flush=True)
    started=time.monotonic()
    subprocess.run([PY,str(HERE/name),*args],check=True)
    return round(time.monotonic()-started,2)

if __name__=="__main__":
    db=get_supabase()
    started=datetime.now(timezone.utc).isoformat()
    claim=db.rpc("claim_daily_market_refresh",{"p_force":os.getenv("FORCE_DAILY_REFRESH","false").lower()=="true"}).execute().data or {}
    if not claim.get("run"):
        print("Daily refresh already completed or claimed by another scheduler; skipping.")
        sys.exit(0)
    run_id=claim["id"]
    timings={}
    try:
        timings["ingest_prices_seconds"]=run("ingest_prices.py","--all","--daily-credit-budget",os.getenv("PRICE_CREDIT_BUDGET","550"))
        price_check=validate(db)
        if price_check["missing_prices"] or price_check["universe_companies"] < 500:
            raise RuntimeError("Price ingestion incomplete for {}: {} companies; aborting before features/scan".format(price_check["expected_market_date"], price_check["price_companies"]))
        timings["features_seconds"]=run("build_daily_price_features.py")
        quality=db.rpc("price_session_quality",{"p_since":(datetime.now(timezone.utc).date()-timedelta(days=29)).isoformat()}).execute().data or {}
        if quality.get("incorrect_labels",0):
            raise RuntimeError(f"Incorrect market-session labels: {quality['incorrect_labels']}")
        timings["scan_seconds"]=run("scan_setups.py")
        timings["evaluation_seconds"]=run("evaluate_signals.py")
        check=validate(db)
        metadata={"timings":timings,"missing_prices":check["missing_prices"],"missing_features":check["missing_features"],"price_session_quality":quality}
        update={"finished_at":datetime.now(timezone.utc).isoformat(),"status":"success" if check["ok"] else "error",
                "expected_market_date":check["expected_market_date"],"latest_price_date":check["latest_price_date"],
                "latest_feature_date":check["latest_feature_date"],"price_companies":check["price_companies"],
                "feature_companies":check["feature_companies"],"error_message":check["error_message"],"metadata":metadata}
        if run_id:
            db.table("pipeline_runs").update(update).eq("id",run_id).execute()
        if not check["ok"]:
            raise RuntimeError(check["error_message"])
        print(f"\nDaily market refresh validated successfully. timings={timings}")
    except Exception as exc:
        if run_id:
            db.table("pipeline_runs").update({"finished_at":datetime.now(timezone.utc).isoformat(),"status":"error",
                "error_message":str(exc)[:2000],"metadata":{"timings":timings}}).eq("id",run_id).execute()
        traceback.print_exc()
        raise
