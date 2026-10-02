import subprocess, sys
from pathlib import Path
from dotenv import load_dotenv

HERE=Path(__file__).resolve().parent
API_DIR=HERE.parent
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")

from app.db.client import get_supabase
from scripts.validate_daily_cycle import validate

PY=sys.executable

def check_readiness(db):
    health=validate(db)
    if not health["ok"]:
        raise RuntimeError(health["error_message"] or "Friday price/features coverage is incomplete")

    expected=health["expected_market_date"]
    runs=(db.table("pipeline_runs").select("status,expected_market_date,latest_price_date,latest_feature_date")
          .eq("pipeline","daily_market_research")
          .order("started_at",desc=True).limit(1).execute().data or [])
    run=runs[0] if runs else {}
    if (run.get("status")!="success" or
            any(run.get(field)!=expected for field in
                ("expected_market_date","latest_price_date","latest_feature_date"))):
        raise RuntimeError(f"Latest daily refresh has not validated market close {expected}; weekly freeze blocked")

    candidates=db.rpc("research_dashboard_candidates").execute().data or []
    ready=[r for r in candidates if r.get("price_date")==expected and r.get("as_of_date")==expected]
    if not ready:
        raise RuntimeError(f"No current setup snapshots for market close {expected}; weekly freeze blocked")
    print(f"Weekly readiness: {expected}, {len(ready)} current setup snapshots")
    return expected

def run(name,*args):
    print(f"\n=== {name} ===")
    subprocess.run([PY,str(HERE/name),*args],check=True)

if __name__=="__main__":
    # Never publish a cohort from Thursday data when Friday's close is expected.
    check_readiness(get_supabase())
    run("evaluate_signals.py")
    run("generate_weekly_signals.py","--top","5","--horizons","5","10","20")
    print("\nWeekly prediction cycle complete.")
