"""Check official filing metadata independently of financial fact extraction."""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR)); load_dotenv(API_DIR / ".env")
from app.db.client import get_supabase
from app.providers.sec import SECProvider
from app.research.company_disclosures import current_reports

PIPELINE = "company_disclosures_refresh"
COLLECTOR = "financial_material_and_insider_reports_v2"


async def refresh(db, provider, max_age_hours=12, delay=.2,lookback_days=90):
    now = datetime.now(timezone.utc)
    companies = db.table("companies").select("id,ticker,cik").eq("is_sp500", True).eq("active", True).order("ticker").execute().data or []
    if not companies:
        raise RuntimeError("No active index companies; filing refresh aborted")
    previous = db.table("pipeline_runs").select("metadata,finished_at").eq("pipeline", PIPELINE).eq("status", "success").order("finished_at", desc=True).limit(1).execute().data or []
    if previous:
        report = previous[0].get("metadata") or {}
        stamp = datetime.fromisoformat(previous[0]["finished_at"].replace("Z", "+00:00"))
        if (timedelta(0) <= now - stamp < timedelta(hours=max_age_hours)
            and report.get("collector") == COLLECTOR
            and report.get('lookback_days')==lookback_days
            and set(report.get("checked_company_ids", [])) == {c["id"] for c in companies}):
            print("Official disclosures were checked recently for the same universe.", flush=True)
            return report
    run = db.table("pipeline_runs").insert({"pipeline": PIPELINE, "status": "running", "started_at": now.isoformat()}).execute().data[0]
    report = {"collector": COLLECTOR, "universe": len(companies), "checked_company_ids": [],
              "missing_cik": [], "errors": [], "filings_received": 0, "lookback_days": lookback_days,
              'historical_universe':'current constituents; historical index membership is not inferred'}
    finalized = False
    try:
        failures = 0
        for company in companies:
            if not company.get("cik"):
                report["missing_cik"].append(company["ticker"])
                continue
            try:
                submissions = await provider.submissions(company["cik"])
                if str(submissions.get("cik", "")).lstrip("0") != str(company["cik"]).lstrip("0"):
                    raise RuntimeError("SEC submission issuer does not match the company's CIK")
                if not isinstance((submissions.get("filings") or {}).get("recent"), dict):
                    raise RuntimeError("SEC submissions response has no recent filing inventory")
                observed=datetime.now(timezone.utc).isoformat()
                if lookback_days>90:
                    submissions=await provider.submission_history(company['cik'],submissions,lookback_days,observed)
                rows = current_reports(company, submissions, observed,lookback_days)
                # Long official-report backfills do not flood the database with
                # years of insider transactions; the daily Form 4 queue stays 90d.
                rows=[r for r in rows if r['form'] not in ('4','4/A') or (now.date()-datetime.fromisoformat(r['filing_date']).date()).days<=90]
            except Exception as exc:
                report["errors"].append({"ticker": company["ticker"], "type": type(exc).__name__})
                failures += 1
                if failures >= 10:
                    report["stopped_after_repeated_failures"] = True
                    break
                await asyncio.sleep(max(0, delay))
                continue
            if rows:
                db.table("company_disclosures").upsert(rows, on_conflict="company_id,accession_number", ignore_duplicates=True, returning="minimal").execute()
                report["filings_received"] += len(rows)
            report["checked_company_ids"].append(company["id"])
            failures = 0
            if len(report["checked_company_ids"]) % 50 == 0:
                print(f"Official filings checked: {len(report['checked_company_ids'])}/{len(companies)}", flush=True)
            await asyncio.sleep(max(0, delay))
        report["checked_companies"] = len(report["checked_company_ids"])
        report["coverage_status"] = "complete" if report["checked_companies"] == len(companies) and companies else "partial"
        status = "success" if report["coverage_status"] == "complete" else "error"
        db.table("pipeline_runs").update({"status": status, "finished_at": datetime.now(timezone.utc).isoformat(), "metadata": report}).eq("id", run["id"]).execute()
        finalized = True
        print(json.dumps({k: v for k, v in report.items() if k != "checked_company_ids"}), flush=True)
        if status == "error":
            raise RuntimeError("Official filing coverage incomplete; successful observations retained")
        return report
    except Exception as exc:
        if not finalized:
            db.table("pipeline_runs").update({"status": "error", "finished_at": datetime.now(timezone.utc).isoformat(), "metadata": report, "error_message": type(exc).__name__}).eq("id", run["id"]).execute()
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-age-hours", type=float, default=12)
    parser.add_argument("--delay", type=float, default=.2)
    parser.add_argument('--lookback-days',type=int,default=90)
    args = parser.parse_args()
    if not 1<=args.lookback_days<=1825:parser.error('lookback must be between 1 and 1825 days')
    asyncio.run(refresh(get_supabase(), SECProvider(), args.max_age_hours, args.delay,args.lookback_days))


if __name__ == "__main__":
    main()
