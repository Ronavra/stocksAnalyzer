"""Refresh independent optional sources and record each one's real result."""
import json
import os
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase


def main():
    db=get_supabase(); started=datetime.now(timezone.utc).isoformat()
    run=db.table("pipeline_runs").insert({"pipeline":"research_enrichment","status":"running","started_at":started}).execute().data[0]
    results={}
    for source,script,args,key in (
        ("forward_estimates","refresh_estimate_snapshots.py",[],None),
        ("news","ingest_news.py",[],"MASSIVE_API_KEY"),
        ("official_filings","refresh_company_disclosures.py",[],"SEC_USER_AGENT"),
        ("vendor_guidance","ingest_massive_guidance.py",["--incremental"],"MASSIVE_API_KEY"),
        ("sec_guidance","enrich_company_disclosures.py",[],"SEC_USER_AGENT"),
    ):
        if key and not os.getenv(key):
            results[source]={"status":"not_configured"}; continue
        # Source scripts sanitize provider errors. Keep logs on the runner;
        # an optional provider failure must not erase other collected data.
        result=subprocess.run([sys.executable,str(API_DIR/"scripts"/script),*args])
        results[source]={"status":"success" if result.returncode==0 else "error","exit_code":result.returncode}
    audit=subprocess.run([sys.executable,str(API_DIR/"scripts"/"check_source_coverage.py")])
    results["coverage_audit"]={"status":"success" if audit.returncode==0 else "error","exit_code":audit.returncode}
    status="success" if all(r["status"]=="success" for r in results.values()) else "error"
    db.table("pipeline_runs").update({"status":status,"finished_at":datetime.now(timezone.utc).isoformat(),"metadata":{"sources":results},
        "error_message":None if status=="success" else "Some optional sources are unavailable; inspect individual source status"}).eq("id",run["id"]).execute()
    print(json.dumps(results))
    if status!="success":
        # Let Actions report partial collection as a failure while retaining
        # the successful independent source observations.
        raise RuntimeError("Research enrichment incomplete; see persisted source statuses")


if __name__=="__main__":
    main()
