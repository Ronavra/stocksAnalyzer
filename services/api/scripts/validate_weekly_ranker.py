"""Validate and record the five-day weekly ranker without changing frozen picks."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))
load_dotenv(API_DIR / ".env")

from app.db.client import get_supabase
from app.research.weekly_ranker import prepare, validate
from app.research.weekly_rank_metrics import RANKER_VERSION, ranker_is_validated


def main():
    db = get_supabase()
    created = db.table("model_validation_runs").insert({"status": "running", "model_version": RANKER_VERSION}).execute().data or []
    if not created:
        raise RuntimeError("Weekly validation run was not recorded")
    run_id = created[0]["id"]
    try:
        report = validate(prepare(db))
        run = {"status": "success", "model_version": RANKER_VERSION, "results": report}
        report["promotion_passed"] = ranker_is_validated(run)
        payload = {"finished_at": datetime.now(timezone.utc).isoformat(), "status": "success",
                   "best_stage": report["selected_variant"], "best_groups": ["price", "context"], "results": report}
        db.table("model_validation_runs").update(payload).eq("id", run_id).execute()
        (API_DIR / "weekly_ranker_validation.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({k: v for k, v in report.items() if k != "holdout_cohorts"}, indent=2), flush=True)
    except Exception as exc:
        db.table("model_validation_runs").update({"status": "error", "finished_at": datetime.now(timezone.utc).isoformat(),
                                                  "error_message": str(exc)[:2000]}).eq("id", run_id).execute()
        raise


if __name__ == "__main__":
    main()
