"""Collect immutable consensus observations across the current S&P universe."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.providers.analyst_consensus import ConsensusProvider, normalize
from app.research.analyst_consensus import load_snapshots,consensus_score

PIPELINE="analyst_consensus_refresh"


def refresh(db,provider,max_age_hours=24,delay=1.1):
    now=datetime.now(timezone.utc)
    companies=db.table("companies").select("id,ticker").eq("is_sp500",True).execute().data or []
    if not companies:
        raise RuntimeError("No current companies; analyst refresh aborted")
    snapshots=load_snapshots(db,(now-timedelta(hours=max_age_hours)).isoformat()) if max_age_hours else []
    fresh=set()
    for row in snapshots:
        data=consensus_score([row],now.date().isoformat(),now=now)
        if data["available"] and row["source"]==provider.source:
            fresh.add(row["company_id"])
    started=now.isoformat()
    created=db.table("pipeline_runs").insert({"pipeline":PIPELINE,"status":"running","started_at":started}).execute().data or []
    run_id=created[0]["id"] if created else None
    report={"source":provider.source,"universe":len(companies),"requested":0,"reused":0,"stored":0,"empty":0,"empty_tickers":[],"errors":[],"current_companies":len(fresh)}
    completed=False
    try:
        failures=0
        for company in companies:
            cid=company["id"]
            if cid in fresh:
                report["reused"]+=1; continue
            report["requested"]+=1
            try:
                records,targets=provider.fetch(company["ticker"])
                observed=datetime.now(timezone.utc).isoformat()
                rows=normalize(cid,records,provider.source,observed,targets)
            except Exception as exc:
                failures+=1
                report["errors"].append({"ticker":company["ticker"],"type":type(exc).__name__})
                rows=None
            if rows:
                # DB failures must abort, rather than be misreported as source gaps.
                db.table("analyst_consensus_snapshots").insert(rows).execute()
                report["stored"]+=len(rows)
                if consensus_score(rows,now.date().isoformat(),now=datetime.now(timezone.utc))["available"]:
                    report["current_companies"]+=1
                failures=0
            elif rows is not None:
                report["empty"]+=1
                report["empty_tickers"].append(company["ticker"])
                failures+=1
            if failures>=10:
                report["stopped_after_repeated_failures"]=True
                break
            if report["requested"]%25==0:
                print(json.dumps({k:v for k,v in report.items() if k not in ("errors","empty_tickers")}),flush=True)
            time.sleep(max(0,delay))
        # A partial refresh is reported honestly; one blocked source does not
        # interrupt prices/financials. No stale values acquire a fresh timestamp.
        report["unattempted"]=len(companies)-report["requested"]-report["reused"]
        report["coverage_status"]="complete" if report["current_companies"]==len(companies) else "partial" if report["current_companies"] else "unavailable"
        status="success" if report["current_companies"] else "error"
        if run_id:
            db.table("pipeline_runs").update({"status":status,"finished_at":datetime.now(timezone.utc).isoformat(),"metadata":report}).eq("id",run_id).execute()
        completed=True
        (API_DIR/"analyst_consensus_refresh.json").write_text(json.dumps(report,indent=2)+"\n")
        print(json.dumps(report,indent=2),flush=True)
        if status=="error":
            raise RuntimeError("No usable analyst consensus collected; analyst contribution remains neutral")
        return report
    except Exception as exc:
        if run_id and not completed:
            db.table("pipeline_runs").update({"status":"error","finished_at":datetime.now(timezone.utc).isoformat(),
                "error_message":type(exc).__name__,"metadata":report}).eq("id",run_id).execute()
        raise


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",choices=("auto","yahoo_finance","finnhub"),default="auto")
    parser.add_argument("--max-age-hours",type=float,default=24)
    parser.add_argument("--delay",type=float,default=1.1)
    args=parser.parse_args()
    refresh(get_supabase(),ConsensusProvider(args.source),args.max_age_hours,args.delay)


if __name__=="__main__":
    main()
