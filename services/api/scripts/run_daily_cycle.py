import subprocess, sys, traceback, time
from datetime import datetime, timezone
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
    created=db.table("pipeline_runs").insert({"pipeline":"daily_market_research","started_at":started,"status":"running"}).execute().data or []
    run_id=created[0]["id"] if created else None
    timings={}
    try:
        timings["ingest_prices_seconds"]=run("ingest_prices.py","--all")
        timings["features_seconds"]=run("build_daily_price_features.py")
        timings["scan_seconds"]=run("scan_setups.py")
        timings["evaluation_seconds"]=run("evaluate_signals.py")
        check=validate(db)
        metadata={"timings":timings,"missing_prices":check["missing_prices"],"missing_features":check["missing_features"]}
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
