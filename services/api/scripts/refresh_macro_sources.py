"""Collect macro context without treating revised CSV history as point-in-time."""
import asyncio
from datetime import datetime
from pathlib import Path
import sys
import httpx
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR));load_dotenv(API_DIR/'.env')
from app.db.client import get_supabase
from app.providers.macro import MacroProvider,SERIES,bls_calendar
from app.research.collection import now,start,finish,check


async def refresh(db,provider):
    run=start(db,'macro_sources_refresh')
    report={'series':{},'errors':[],'calendar_events':0,'historical_vintages':bool(provider.api_key)}
    try:
        async with httpx.AsyncClient(timeout=60,headers={'User-Agent':'StocksAnalyzer public macro research'}) as client:
            for series in SERIES:
                try:
                    observed=now(); rows=await provider.observations(client,series,observed)
                    if not rows: raise ValueError('No numeric observations')
                except Exception as exc:
                    report['errors'].append({'series':series,'type':type(exc).__name__})
                    check(db,'macro',series,'error',error_type=type(exc).__name__);continue
                for offset in range(0,len(rows),500):
                    db.table('macro_observations').upsert(rows[offset:offset+500],on_conflict='series_id,observation_date,source,fingerprint',ignore_duplicates=True,returning='minimal').execute()
                latest=max(x['observation_date'] for x in rows)
                fresh=(datetime.fromisoformat(observed).date()-datetime.fromisoformat(latest).date()).days<=SERIES[series][2]
                vintage=all(x.get('vintage_date') is not None for x in rows)
                report['series'][series]={'rows':len(rows),'latest':latest,'fresh':fresh,'source':rows[0]['source'],'historical_vintages':vintage}
                check(db,'macro',series,'success' if fresh else 'partial',latest=latest,historical_vintages=vintage,max_age_days=SERIES[series][2],observation_source=rows[0]['source'])
            try:
                response=await client.get('https://www.bls.gov/schedule/news_release/bls.ics',timeout=20);response.raise_for_status()
                events=bls_calendar(response.text,now())
            except Exception as exc:
                report['errors'].append({'source':'bls_calendar','type':type(exc).__name__})
                check(db,'macro','bls_calendar','error',error_type=type(exc).__name__)
            else:
                for offset in range(0,len(events),500):
                    db.table('economic_calendar_observations').upsert(events[offset:offset+500],on_conflict='source,source_record_id,observed_at',ignore_duplicates=True,returning='minimal').execute()
                report['calendar_events']=len(events)
                check(db,'macro','bls_calendar','success',events=len(events),snapshot_at=events[0]['observed_at'],fed_and_bea_calendars_collected=False)
        report['historical_vintages']=bool(report['series']) and all(x['historical_vintages'] for x in report['series'].values())
        return finish(db,run,report)
    except Exception as exc:
        report['errors'].append({'type':type(exc).__name__});finish(db,run,report);raise


if __name__=='__main__':
    if asyncio.run(refresh(get_supabase(),MacroProvider()))!='success':sys.exit(1)
