"""Capture one immutable fiscal-consensus observation per company/day/period."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR)); load_dotenv(API_DIR / ".env")
from app.db.client import get_supabase
from app.providers.estimate_consensus import EstimateConsensusProvider, normalize
from app.research.prospective_metrics import paged

PIPELINE = "estimate_consensus_refresh"
CONFLICT = "company_id,captured_date,fiscal_period_end,period_type,source"


def refresh(db, provider, delay=1.1, limit=None):
    now = datetime.now(timezone.utc)
    companies = db.table("companies").select("id,ticker").eq("is_sp500", True).eq("active", True).order("ticker").execute().data or []
    if not companies:
        raise RuntimeError("No active index companies; estimate refresh aborted")
    # Reuse this UTC day's observation. Never overwrite it with a later fetch
    # and thereby change the inputs behind an earlier signal.
    existing = paged(db.table("estimate_snapshots").select("id,company_id,eps_consensus,revenue_consensus")
                     .eq("source", provider.source).eq("captured_date", now.date().isoformat()).order("id"))
    fresh = {r["company_id"] for r in existing if r.get("eps_consensus") is not None or r.get("revenue_consensus") is not None}
    run = db.table("pipeline_runs").insert({"pipeline": PIPELINE, "status": "running", "started_at": now.isoformat()}).execute().data[0]
    report = {"source": provider.source, "universe": len(companies), "requested": 0,
              "reused": 0, "stored": 0, "empty_tickers": [], "errors": [],
              "current_companies": len(fresh & {c['id'] for c in companies}),
              "archive_starts_at_actual_observation": True, "eps_basis": "unknown"}
    finalized = False
    try:
        failures = 0
        for company in companies:
            if company["id"] in fresh:
                report["reused"] += 1
                continue
            if limit is not None and report["requested"] >= limit:
                continue
            report["requested"] += 1
            try:
                records = provider.fetch(company["ticker"])
                rows = normalize(company["id"], records, datetime.now(timezone.utc).isoformat())
            except Exception as exc:
                # No provider URLs, authentication data or response bodies in logs.
                report["errors"].append({"ticker": company["ticker"], "type": type(exc).__name__})
                rows = None
            if rows:
                # DB failures abort; they are not misreported as missing estimates.
                db.table("estimate_snapshots").upsert(rows, on_conflict=CONFLICT, ignore_duplicates=True, returning="minimal").execute()
                report["stored"] += len(rows)
                report["current_companies"] += 1
                failures = 0
            else:
                failures += 1
                if rows is not None:
                    report["empty_tickers"].append(company["ticker"])
            if failures >= 10:
                report["stopped_after_repeated_failures"] = True
                break
            if report["requested"] % 25 == 0:
                print(json.dumps({k: v for k, v in report.items() if k not in ("errors", "empty_tickers")}), flush=True)
            time.sleep(max(0, delay))
        report["unattempted"] = len(companies) - report["requested"] - report["reused"]
        report["coverage_status"] = "complete" if report["current_companies"] == len(companies) else "partial" if report["current_companies"] else "unavailable"
        status = "error" if report["errors"] or report["unattempted"] or not report["current_companies"] else "success"
        db.table("pipeline_runs").update({"status": status, "finished_at": datetime.now(timezone.utc).isoformat(), "metadata": report}).eq("id", run["id"]).execute()
        finalized = True
        print(json.dumps(report), flush=True)
        if status == "error":
            raise RuntimeError("Estimate collection incomplete; successful observations retained")
        return report
    except Exception as exc:
        if not finalized:
            db.table("pipeline_runs").update({"status": "error", "finished_at": datetime.now(timezone.utc).isoformat(),
                "metadata": report, "error_message": type(exc).__name__}).eq("id", run["id"]).execute()
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=1.1)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    refresh(get_supabase(), EstimateConsensusProvider(), args.delay, args.limit)


if __name__ == "__main__":
    main()
