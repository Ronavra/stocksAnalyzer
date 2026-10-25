"""Record twenty-session research or an explicit archive/history blocker."""
import argparse
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import sys
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1];sys.path.insert(0,str(API_DIR));load_dotenv(API_DIR/'.env')
from app.db.client import get_supabase
from app.research.twenty_day_model import VERSION,PROTOCOL,prepare,validate


def run(db,readiness_only=False):
    db.rpc('reconcile_predictive_research_leases').execute()
    readiness=db.rpc('research_predictive_readiness').execute().data or {}
    claim=db.rpc('claim_predictive_validation',{'p_model_version':VERSION,'p_claim':True}).execute().data or {}
    if not claim.get('run'):return {'outcome':'already_running','promotion_passed':False}
    run_id=claim['id'];now=datetime.now(timezone.utc)
    report={'evaluation_protocol':PROTOCOL,'model_version':VERSION,'primary_horizon_days':20,
            'max_positions':10,'promotion_passed':False,'active_selection_changed':False}
    try:
        full_history=not bool(getattr(db,'history_policy',None)) or bool(getattr(db,'archive',None))
        if readiness_only or not full_history:
            report.update(outcome='readiness_only' if full_history else 'deferred_archive_required',
                full_history_available=full_history,history=readiness.get('history'),quality=readiness.get('quality'),
                required_local_command='python scripts/run_local_model_validation.py',
                blocked_reason='Full price archive and observed historical inputs are required for actual training.')
        else:
            report=validate(prepare(db))
            report['full_history_available']=True
        payload={'status':'success','finished_at':datetime.now(timezone.utc).isoformat(),
            'best_stage':report.get('selected_family') or 'blocked','best_groups':[], 'results':report}
        saved=db.table('model_validation_runs').update(payload).eq('id',run_id).eq('status','running').gte('started_at',(now-timedelta(hours=6)).isoformat()).execute().data
        if not saved:raise RuntimeError('Twenty-session research lease expired; results withheld')
        (API_DIR/'twenty_day_research.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2),flush=True)
        return report
    except Exception as exc:
        db.table('model_validation_runs').update({'status':'error','finished_at':datetime.now(timezone.utc).isoformat(),
            'error_message':type(exc).__name__+': twenty-session research failed'}).eq('id',run_id).eq('status','running').execute()
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--readiness-only',action='store_true');args=parser.parse_args()
    run(get_supabase(),args.readiness_only)
