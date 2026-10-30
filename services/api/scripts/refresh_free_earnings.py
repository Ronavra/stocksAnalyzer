"""Free public calendars and paired EPS results; no paid Benzinga requests."""
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/'.env')
from app.db.client import get_supabase
from app.providers.free_earnings import YahooEarningsProvider, AlphaCalendarProvider, yahoo_payload, calendar_row
from app.research.free_calendar import calendar_assessment
from app.market_calendar import latest_session_close, NY
from app.providers.corporate_calendar import projected_dividends
from app.research.collection import save_events


def store_calendar_snapshot(db, snapshot, retries=3):
    """Retry transient gateway failures without duplicating an ambiguous write."""
    from postgrest.exceptions import APIError
    import random
    for attempt in range(retries):
        try:
            db.table('earnings_calendar_snapshots').insert(snapshot).execute()
            return
        except APIError as exc:
            code=str(getattr(exc,'code',''))
            if code not in ('502','503','504','520','522','524') or attempt==retries-1:
                raise
            # A gateway can fail *after* Postgres committed. Check the
            # exact source/timestamp before retrying this insert.
            existing=(db.table('earnings_calendar_snapshots')
                      .select('id').eq('company_id',snapshot['company_id'])
                      .eq('source',snapshot['source']).eq('observed_at',snapshot['observed_at'])
                      .limit(1).execute().data or [])
            if existing:return
            time.sleep(min(8,2**attempt)+random.random())


def fresh_company_ids(previous, now):
    # A recent pre-close fetch cannot cover a newly completed market session.
    close = latest_session_close(now).astimezone(timezone.utc)
    fresh = set()
    for row in previous:
        stamp = datetime.fromisoformat(row['observed_at'].replace('Z','+00:00'))
        if (row.get('source') == 'yahoo_finance' and row.get('status') == 'observed'
            and timedelta(0) <= now-stamp < timedelta(hours=4) and stamp >= close
            and any(d >= now.astimezone(NY).date().isoformat() for d in row.get('dates') or [])):
            fresh.add(row['company_id'])
    return fresh


def refresh(db, provider=None, delay=0.6, now=None):
    now = now or datetime.now(timezone.utc)
    companies = db.table('companies').select('id,ticker').eq('is_sp500',True).order('ticker').execute().data or []
    if not companies:
        raise RuntimeError('Free earnings refresh requires a company universe')
    claim = db.rpc('claim_free_earnings_refresh').execute().data or {}
    if not claim.get('run'):
        # A concurrent job is not a successful refresh of this caller.
        raise RuntimeError('Free earnings collection is already running; retry after it completes')
    run_id = claim['id']; provider = provider or YahooEarningsProvider()
    report = {'universe':len(companies),'requested':0,'reused':0,'events_stored':0,'errors':[],
              'projected_dividends_stored':0,'alpha_calendar':'not_configured','paid_endpoints_called':False,'revenue_surprise_available':False}
    try:
        previous = db.rpc('free_earnings_calendar').execute().data or []
        fresh = fresh_company_ids(previous, now)
        key = os.getenv('ALPHA_VANTAGE_API_KEY')
        if key and db.rpc('claim_alpha_earnings_calendar').execute().data:
            try:
                bulk = AlphaCalendarProvider(key).fetch()
                stamp = datetime.now(timezone.utc).isoformat()
                rows = [calendar_row(c['id'],'alphavantage',bulk[c['ticker']],stamp)
                        for c in companies if c['ticker'] in bulk]
                if rows:
                    db.table('earnings_calendar_snapshots').insert(rows).execute()
                report['alpha_calendar'] = 'observed'
                report['alpha_companies'] = len(rows)
            except Exception as exc:
                report['alpha_calendar'] = type(exc).__name__
        elif key:
            report['alpha_calendar'] = 'daily_request_already_reserved'
        consecutive = 0
        deadline = time.monotonic()+45*60
        for company in companies:
            if company['id'] in fresh:
                report['reused'] += 1
                continue
            report['requested'] += 1
            try:
                calendar, events = provider.fetch(company['ticker'])
                observed = datetime.now(timezone.utc).isoformat()
                snapshot, payload = yahoo_payload(company['id'],calendar,events,observed)
                actions=projected_dividends(company['id'],calendar,observed,company['ticker'])
            except Exception as exc:
                report['errors'].append({'ticker':company['ticker'],'type':type(exc).__name__})
                snapshot = calendar_row(company['id'],'yahoo_finance',[],datetime.now(timezone.utc).isoformat())
                snapshot['status'] = 'error'; payload = []; actions=[]
            # DB errors abort: never hide persistence failures as provider gaps.
            db.table('earnings_calendar_snapshots').insert(snapshot).execute()
            if actions:
                save_events(db,actions)
                report['projected_dividends_stored']+=len(actions)
            if payload:
                db.table('earnings_events').upsert(payload,on_conflict='company_id,reported_date,source').execute()
                report['events_stored'] += len(payload)
            consecutive = consecutive+1 if snapshot['status'] != 'observed' else 0
            if report['requested'] % 25 == 0:
                print(json.dumps({k:v for k,v in report.items() if k!='errors'}),flush=True)
            if consecutive >= 10 or time.monotonic() >= deadline:
                report['stopped_after_repeated_failures_or_deadline'] = True
                break
            time.sleep(max(0,delay))
        checks = db.rpc('free_earnings_calendar').execute().data or []
        statuses = calendar_assessment(checks,[c['id'] for c in companies],now.date().isoformat())
        report['current_calendars'] = sum(r['calendar_status']=='current' for r in statuses.values())
        report['unknown_tickers'] = [c['ticker'] for c in companies if statuses[c['id']]['calendar_status']!='current']
        report['unattempted'] = len(companies)-report['requested']-report['reused']
        report['coverage_status'] = 'complete' if report['current_calendars']==len(companies) else 'partial'
        if not report['current_calendars']:
            raise RuntimeError('No fresh earnings calendars; live publication blocked')
        finished = datetime.now(timezone.utc).isoformat()
        db.table('pipeline_runs').update({'status':'success','finished_at':finished,'metadata':report}).eq('id',run_id).eq('status','running').execute()
        (API_DIR/'free_earnings_refresh.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report),flush=True)
        return report
    except Exception as exc:
        db.table('pipeline_runs').update({'status':'error','finished_at':datetime.now(timezone.utc).isoformat(),
            'metadata':report,'error_message':type(exc).__name__+': free earnings collection incomplete'}).eq('id',run_id).eq('status','running').execute()
        raise


if __name__ == '__main__':
    refresh(get_supabase())
