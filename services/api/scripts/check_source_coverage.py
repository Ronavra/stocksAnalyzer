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
        from postgrest.exceptions import APIError
        try:
            snapshot=db.rpc('research_dashboard_data_audit').execute().data or {}
            coverage=coverage_from_inventory(snapshot.get('inventory') or [],snapshot.get('calendars') or [],
                snapshot.get('financial_report') or {},snapshot.get('source_checks') or [])
        except APIError as exc:
            if str(getattr(exc,'code',None)) != '57014':
                raise
            # A global inventory times out as coverage expands. Partition by
            # issuer using the existing filtered, indexed SQL RPC. No old
            # snapshot is silently passed off as fresh and no issuer is skipped.
            print('Global audit timed out; recomputing each issuer independently',flush=True)
            companies=db.table('companies').select('id').eq('is_sp500',True).eq('active',True).order('id').execute().data or []
            if not companies:raise RuntimeError('Source coverage universe missing')
            raw=[]
            for i,company in enumerate(companies,1):
                item=db.rpc('research_source_inventory',{'p_company_id':company['id']}).execute().data or []
                if len(item)!=1 or item[0].get('company_id')!=company['id']:
                    raise RuntimeError('Incomplete issuer source inventory')
                raw.extend(item)
                if i%100==0:print(json.dumps({'audited_companies':i,'universe':len(companies)}),flush=True)
            calendar=[]
            for i in range(0,len(companies),50):
                ids=[c['id'] for c in companies[i:i+50]]
                calendar.extend(db.rpc('free_earnings_calendar',{'p_company_ids':ids}).execute().data or [])
            reports=(db.table('pipeline_runs').select('metadata,finished_at,status')
                     .eq('pipeline','research_sources_refresh').order('started_at',desc=True)
                     .limit(10).execute().data or [])
            financial=next((x for x in reports if (x.get('metadata') or {}).get('financial_audit')), {})
            checks=(db.table('pipeline_runs').select('pipeline,status,started_at,finished_at')
                    .in_('pipeline',['free_earnings_refresh','research_sources_refresh','company_disclosures_refresh',
                      'estimate_consensus_refresh','news_refresh','sec_guidance_refresh','analyst_consensus_refresh',
                      'official_documents_refresh','insider_transactions_refresh','public_ownership_actions_refresh',
                      'corporate_actions_refresh','macro_sources_refresh']).order('started_at',desc=True)
                    .limit(100).execute().data or [])
            latest={}
            for check in checks:latest.setdefault(check['pipeline'],check)
            coverage=coverage_from_inventory(raw,calendar,financial,list(latest.values()))
            if len(coverage['companies'])!=len(companies):
                raise RuntimeError('Partitioned source audit is not complete')
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
