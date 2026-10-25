"""Collect paginated dividend/split calendars without per-issuer quota bursts."""
import asyncio
import os
from datetime import date,timedelta
from pathlib import Path
import sys
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR));load_dotenv(API_DIR/'.env')
from app.db.client import get_supabase
from app.providers.twelvedata import TwelveDataProvider
from app.research.evidence import corporate_actions
from app.research.collection import now,start,finish,check,save_events


def free_action_coverage(db):
    from app.research.prospective_metrics import paged
    run=start(db,'corporate_actions_refresh')
    report={'errors':[],'coverage_status':'partial','source_policy':'free-observed-actions-v1',
        'paid_calendar_endpoints_called':False,'upcoming_split_calendar_available':False,
        'mergers_and_spinoffs_collected':False}
    try:
        since=(date.today()-timedelta(days=2)).isoformat()+'T00:00:00Z'
        checks=paged(db.table('research_collection_checks').select('id,company_id').eq('family','actions')
            .eq('source','yahoo_actions').eq('status','success').gte('checked_at',since).order('id'))
        dividends=paged(db.table('research_evidence_events').select('id,company_id').eq('source','yahoo_calendar')
            .eq('kind','dividend').gte('event_date',date.today().isoformat()).gte('observed_at',since).order('id'))
        report.update(historical_action_companies=len({r['company_id'] for r in checks}),
            projected_dividend_companies=len({r['company_id'] for r in dividends}))
        if not checks and not dividends:report['unavailable']=True
        check(db,'actions','free_observed_actions','partial' if checks or dividends else 'error',**report)
        return finish(db,run,report)
    except Exception as exc:
        report['errors'].append({'type':type(exc).__name__});finish(db,run,report);raise


async def refresh(db,provider=None,delay=10):
    if provider is None:return free_action_coverage(db)
    run=start(db,'corporate_actions_refresh')
    report={'checked':0,'events':0,'errors':[],'dividends_and_splits_only':True,'calendar_pages':0}
    try:
        companies=db.table('companies').select('id,ticker').eq('active',True).eq('is_sp500',True).execute().data or []
        by_symbol={provider.provider_symbol(c['ticker']):c for c in companies}
        since=(date.today()-timedelta(days=370)).isoformat();until=(date.today()+timedelta(days=120)).isoformat()
        for endpoint,kind in [('dividends_calendar','dividend'),('splits_calendar','split')]:
            collected={c['id']:0 for c in companies};seen=set()
            for page in range(1,31):
                try:
                    data,_=await provider._get(endpoint,country='US',start_date=since,end_date=until,outputsize=500,page=page)
                    if not isinstance(data,list):raise ValueError('Calendar response is not an event array')
                    identities={(x.get('symbol'),x.get('ex_date') or x.get('date')) for x in data}
                    if data and identities<=seen:raise ValueError('Corporate calendar pagination stalled')
                    seen.update(identities);rows=[]
                    for item in data:
                        c=by_symbol.get(item.get('symbol'))
                        if not c:continue
                        normalized={'meta':{'currency':item.get('currency')},'dividends' if kind=='dividend' else 'splits':[item]}
                        events=corporate_actions(c['id'],normalized,kind,now());rows.extend(events);collected[c['id']]+=len(events)
                except Exception as exc:
                    report['errors'].append({'endpoint':endpoint,'type':type(exc).__name__})
                    check(db,'actions','twelvedata_'+endpoint,'error',error_type=type(exc).__name__)
                    return finish(db,run,report)
                for offset in range(0,len(rows),500):save_events(db,rows[offset:offset+500])
                report['calendar_pages']+=1;report['events']+=len(rows)
                if len(data)<500:break
                await asyncio.sleep(delay)
            else:
                raise ValueError('Corporate calendar page limit reached')
            checks=[{'company_id':c['id'],'family':'actions','source':'twelvedata_'+endpoint,'status':'success','checked_at':now(),
                     'metadata':{'events':collected[c['id']],'lookback_days':370,'future_days':120,'mergers_and_spinoffs_collected':False}} for c in companies]
            for offset in range(0,len(checks),500):db.table('research_collection_checks').insert(checks[offset:offset+500],returning='minimal').execute()
            await asyncio.sleep(delay)
        report['checked']=len(companies)
        return finish(db,run,report)
    except Exception as exc:
        report['errors'].append({'type':type(exc).__name__});finish(db,run,report);raise


if __name__=='__main__':
    provider=TwelveDataProvider() if os.getenv('ENABLE_TWELVE_ACTIONS_CALENDAR','false').lower()=='true' else None
    if asyncio.run(refresh(get_supabase(),provider))!='success':sys.exit(1)
