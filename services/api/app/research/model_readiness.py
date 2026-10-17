"""Execution readiness is independent from a successful predictive validation."""
from datetime import datetime, timedelta, timezone

LEASE_HOURS = 6


def execution_status(run, now=None):
    if not run:
        return {"status": "not_run", "validated": False}
    result = dict(run)
    now = now or datetime.now(timezone.utc)
    try:
        started = datetime.fromisoformat(run["started_at"].replace("Z", "+00:00"))
        if run.get("status") == "running" and now - started > timedelta(hours=LEASE_HOURS):
            result.update(status="interrupted", error_message="Validation exceeded its six-hour lease; no model was promoted.")
    except (KeyError, ValueError, TypeError):
        if run.get("status") == "running":
            result.update(status="unknown", error_message="Validation start time is unavailable.")
    result["validated"] = False
    return result


def record_history_gate(db, now=None):
    now = now or datetime.now(timezone.utc)
    full_history = not bool(getattr(db, "history_policy", None)) or bool(getattr(db, "archive", None))
    # Reconcile abandoned runs without claiming a training slot on this host.
    db.rpc("claim_predictive_validation", {"p_model_version": "", "p_claim": False}).execute()
    report = {"outcome": "ready" if full_history else "deferred_archive_required",
              "full_history_available": full_history, "validated": False,
              "reason": None if full_history else "Run local model validation on the computer holding LOCAL_MARKET_ARCHIVE."}
    db.table("pipeline_runs").insert({"pipeline": "model_validation_execution", "status": "success",
        "started_at": now.isoformat(), "finished_at": now.isoformat(), "metadata": report}).execute()
    return report
