"""Idempotent, bounded history repair; never rewrites frozen recommendations."""
import json
import sys
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/'.env')
from app.db.client import get_supabase

REVISION='market-session-history-v1'

def main():
    db=get_supabase()
    previous=(db.table('pipeline_runs').select('id').eq('pipeline','research_history_repair')
              .eq('status','success').contains('metadata',{'revision':REVISION}).limit(1).execute().data or [])
    if previous:
        print('This history revision has already been repaired; skipping.')
        return
    created=db.table('pipeline_runs').insert({'pipeline':'research_history_repair','status':'running',
        'started_at':datetime.now(timezone.utc).isoformat(),'metadata':{'revision':REVISION}}).execute().data
    run_id=created[0]['id']
    report={'revision':REVISION,'windows':[],'updated_feature_rows':0}
    try:
        # Try the primary account, then corroborated free fallback for omitted sessions.
        gaps=db.rpc('price_history_gaps',{'p_since':'2026-07-01','p_until':date.today().isoformat()}).execute().data or []
        if gaps:
            subprocess.run([sys.executable,str(API_DIR/'scripts/ingest_prices.py'),'--tickers',
                            *[g['ticker'] for g in gaps],'--repair-since','2026-07-01',
                            '--daily-credit-budget','90'],check=True)
        earliest=(db.table('price_features').select('feature_date').order('feature_date').limit(1).execute().data or [])
        if not earliest: raise RuntimeError('No features to repair')
        start=date.fromisoformat(earliest[0]['feature_date'])
        while start<=date.today():
            ds=start.isoformat()
            result=db.rpc('repair_price_feature_labels',{'p_since':ds}).execute().data
            quality=db.rpc('price_session_quality',{'p_since':ds}).execute().data
            if quality['incorrect_labels']:
                raise RuntimeError(f"Label repair failed for {ds}: {quality['incorrect_labels']}")
            report['updated_feature_rows']+=result['updated_feature_rows']
            report['windows'].append(quality)
            print(json.dumps({'window':ds,**result,'quality':quality}),flush=True)
            if len(report['windows'])%10==0:
                db.table('pipeline_runs').update({'metadata':report}).eq('id',run_id).execute()
            start+=timedelta(days=30)
        recent=db.rpc('price_session_quality',{'p_since':(date.today()-timedelta(days=29)).isoformat()}).execute().data
        recent['gaps']=db.rpc('price_history_gaps',{'p_since':(date.today()-timedelta(days=90)).isoformat(),'p_until':date.today().isoformat()}).execute().data or []
        if recent['gaps']: raise RuntimeError(f"Recent provider gaps unresolved: {recent['gaps']}")
        report['latest_quality']=recent
        subprocess.run([sys.executable,str(API_DIR/'scripts/scan_setups.py')],check=True)
        subprocess.run([sys.executable,str(API_DIR/'scripts/evaluate_signals.py')],check=True)
        db.table('pipeline_runs').update({'status':'success','finished_at':datetime.now(timezone.utc).isoformat(),
            'metadata':report}).eq('id',run_id).execute()
    except Exception as exc:
        db.table('pipeline_runs').update({'status':'error','finished_at':datetime.now(timezone.utc).isoformat(),
            'error_message':str(exc)[:2000],'metadata':report}).eq('id',run_id).execute()
        raise

if __name__=='__main__': main()
