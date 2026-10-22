"""Persist a bounded audit; success means checked, not complete or predictive."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR)); load_dotenv(API_DIR / ".env")
from app.db.client import get_supabase
from app.research.source_coverage import coverage_from_inventory


def main():
    db = get_supabase()
    started = datetime.now(timezone.utc).isoformat()
    run = db.table("pipeline_runs").insert({"pipeline": "source_coverage_audit", "status": "running", "started_at": started}).execute().data[0]
    try:
        snapshot=db.rpc('research_dashboard_data_audit').execute().data or {}
        coverage=coverage_from_inventory(snapshot.get('inventory') or [],snapshot.get('calendars') or [],
            snapshot.get('financial_report') or {},snapshot.get('source_checks') or [])
        if not coverage["companies"]:
            raise RuntimeError("Source inventory contains no companies")
        report = {"universe": len(coverage["companies"]), "families": coverage["families"],
                  "source_checks": coverage["source_checks"], "coverage_status": "partial",
                  "all_major_data_complete": False, "validated_predictive_value": False}
        db.table("pipeline_runs").update({"status": "success", "finished_at": datetime.now(timezone.utc).isoformat(), "metadata": report}).eq("id", run["id"]).execute()
        print(json.dumps(report), flush=True)
    except Exception as exc:
        db.table("pipeline_runs").update({"status": "error", "finished_at": datetime.now(timezone.utc).isoformat(), "error_message": type(exc).__name__}).eq("id", run["id"]).execute()
        raise


if __name__ == "__main__":
    main()
