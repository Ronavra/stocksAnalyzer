"""Persist only exact, basis-consistent guidance/consensus pairs."""
from collections import Counter
from datetime import datetime,timezone,timedelta
from pathlib import Path
import sys,json
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1];sys.path.insert(0,str(API_DIR));load_dotenv(API_DIR/'.env')
from app.db.client import get_supabase
from app.research.guidance_matching import match
from app.research.collection import start,finish,now
from app.research.prospective_metrics import paged


def refresh(db):
    run=start(db,'guidance_consensus_matching');report={'errors':[],'checked':0,'matched':0,'reasons':{}}
    try:
        guides=paged(db.table('corporate_guidance_events').select('*').gte('event_date',(datetime.now(timezone.utc)-timedelta(days=90)).date().isoformat()).order('id'))
        reasons=Counter()
        for g in guides:
            report['checked']+=1
            estimates=paged(db.table('estimate_snapshots').select('*').eq('company_id',g['company_id']).order('id'))
            rows,reason=match(g,estimates,now());reasons[reason]+=1
            if rows:
                db.table('guidance_consensus_matches').upsert(rows,on_conflict='guidance_event_id,estimate_snapshot_id,metric',ignore_duplicates=True,returning='minimal').execute()
                report['matched']+=len(rows)
        report['reasons']=dict(reasons);report['coverage_status']='partial' if report['matched'] else 'building'
        return finish(db,run,report)
    except Exception as exc:
        report['errors'].append({'type':type(exc).__name__});finish(db,run,report);raise

if __name__=='__main__':refresh(get_supabase())
