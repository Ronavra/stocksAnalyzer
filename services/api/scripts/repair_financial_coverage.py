"""Bounded repair of reported facts; unsupported fields remain unknown."""
import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime,timezone,timedelta
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR));load_dotenv(API_DIR/".env")
from app.db.client import get_supabase


def repair_targets(audit,limit):
    core={"revenue","net_income","eps_diluted"}
    rows=[r for r in audit.get("companies",[]) if r.get("missing_required_fields",r.get("missing_fields",[]))]
    def priority(row):
        missing=row.get("missing_required_fields",row.get("missing_fields",[]))
        return (-len(core & set(missing)),row.get("ticker", ""))
    rows.sort(key=priority)
    return rows[:limit]


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--limit",type=int,default=25);args=parser.parse_args()
    if not 1<=args.limit<=50: raise ValueError("Repair batch must contain 1–50 companies")
    db=get_supabase()
    runs=db.table("pipeline_runs").select("metadata").eq("pipeline","research_sources_refresh").order("started_at",desc=True).limit(8).execute().data or []
    audit=next(((r.get("metadata") or {}).get("financial_audit") for r in runs if ((r.get("metadata") or {}).get("financial_audit") or {}).get("scope")=="full_universe"),None)
    if not audit: raise RuntimeError("A full-universe filing audit is required before targeted repair")
    checked=datetime.fromisoformat(audit["finished_at"].replace("Z","+00:00"))
    if datetime.now(timezone.utc)-checked>timedelta(hours=48): raise RuntimeError("Refresh the full SEC audit before repairing field coverage")
    recent=db.table("pipeline_runs").select("metadata").eq("pipeline","financial_coverage_repair").eq("status","success").gte("started_at",(datetime.now(timezone.utc)-timedelta(days=7)).isoformat()).order("started_at",desc=True).limit(10).execute().data or []
    already={ticker for run in recent for ticker in (run.get("metadata") or {}).get("requested_tickers",[])}
    pending={**audit,"companies":[r for r in audit.get("companies",[]) if r.get("ticker") not in already]}
    targets=repair_targets(pending,args.limit)
    report={"requested_tickers":[r["ticker"] for r in targets],"missing_fields":dict(Counter(k for r in targets for k in r.get("missing_required_fields",r.get("missing_fields",[])))),
            "missing_is_not_zero":True,"historical_publications_changed":False}
    started=datetime.now(timezone.utc).isoformat()
    try:
        if targets:
            subprocess.run([sys.executable,str(API_DIR/"scripts"/"ingest_sec_fundamentals.py"),"--repair-fields","--tickers",*[r["ticker"] for r in targets]],check=True,cwd=API_DIR,timeout=30*60)
        if targets:
            repaired=json.loads((API_DIR/"sec_fundamentals_audit.json").read_text())
            report["outcome"]="checked_partial"
            report["after"]=repaired.get("summary")
            report["required_fields_missing_before"]=sum(len(r.get("missing_required_fields",r.get("missing_fields",[]))) for r in targets)
            report["required_fields_missing_after"]=sum(len(r.get("missing_required_fields",r.get("missing_fields",[]))) for r in repaired.get("companies",[]))
            report["remaining"]= [{"ticker":r["ticker"],"missing_fields":r.get("missing_required_fields",[]),"status":r["status"]} for r in repaired.get("companies",[])]
        db.table("pipeline_runs").insert({"pipeline":"financial_coverage_repair","status":"success","started_at":started,
            "finished_at":datetime.now(timezone.utc).isoformat(),"metadata":report}).execute()
        print(json.dumps(report),flush=True)
    except Exception as exc:
        db.table("pipeline_runs").insert({"pipeline":"financial_coverage_repair","status":"error","started_at":started,
            "finished_at":datetime.now(timezone.utc).isoformat(),"metadata":report,"error_message":str(exc)[:500]}).execute()
        raise


if __name__=="__main__":main()
