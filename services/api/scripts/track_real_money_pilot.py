"""Track frozen weekly picks as a $1,000-per-name assumed-open research pilot.

No brokerage interaction, no invented fills, no retroactive selection.
"""
from datetime import datetime, date, timezone
from pathlib import Path
import json
import sys

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
from dotenv import load_dotenv
load_dotenv(API_DIR/'.env')
from app.db.client import get_supabase

PILOT_ID='weekly-2026-10-27'
COHORT='2026-10-23'
TRADE_DATE='2026-10-27'
USD_EACH=1000
EXPECTED=('COF','UBER','NVDA','SYF','DECK')
BENCHMARK='SPY'


def freeze(db):
    cohort=(db.table('recommendation_cohorts').select('signal_date,status,metadata')
            .eq('signal_date',COHORT).single().execute().data)
    if not cohort or cohort['status']!='published':
        raise RuntimeError('Pilot needs a published, immutable cohort')
    picks=cohort['metadata'].get('picks',[])
    tickers=tuple(p.get('ticker') for p in picks)
    if tickers!=EXPECTED or len(set(tickers))!=5:
        raise RuntimeError('Published cohort has changed; refuse to rewrite pilot')
    existing=(db.table('research_pilots').select('pilot_id,cohort_date,trade_date')
              .eq('pilot_id',PILOT_ID).execute().data or [])
    if not existing:
        db.table('research_pilots').insert(dict(pilot_id=PILOT_ID,cohort_date=COHORT,
               trade_date=TRADE_DATE)).execute()
    elif existing[0]['cohort_date']!=COHORT or existing[0]['trade_date']!=TRADE_DATE:
        raise RuntimeError('Pilot identity or entry date differs from frozen plan')
    recorded=(db.table('research_pilot_positions').select('ticker,rank,target_usd')
              .eq('pilot_id',PILOT_ID).execute().data or [])
    if recorded:
        if sorted((r['ticker'],int(r['rank']),float(r['target_usd'])) for r in recorded)!=sorted(
                (ticker,i,USD_EACH) for i,ticker in enumerate(EXPECTED,1)):
            raise RuntimeError('Existing pilot positions differ from frozen plan')
    else:
        db.table('research_pilot_positions').insert([
            dict(pilot_id=PILOT_ID,company_id=p['company_id'],ticker=p['ticker'],
                 rank=i,target_usd=USD_EACH)
            for i,p in enumerate(picks,1)]).execute()
    return picks


def rows_on(db,day):
    tickers=EXPECTED+(BENCHMARK,)
    companies=(db.table('companies').select('id,ticker').in_('ticker',list(tickers))
               .execute().data or [])
    by_ticker={r['ticker']:r['id'] for r in companies}
    if set(by_ticker)!=set(tickers):raise RuntimeError('Pilot or SPY ticker missing')
    rows=(db.table('price_history').select('company_id,price_date,open,close,captured_at')
          .in_('company_id',list(by_ticker.values())).eq('price_date',day)
          .order('captured_at',desc=True).execute().data or [])
    values={r['company_id']:r for r in rows}
    return {t:values.get(cid) for t,cid in by_ticker.items()}


def positive(v):
    try:
        n=float(v)
        return n if 0<n<float('inf') else None
    except (ValueError,TypeError):return None


def update(db,today=None):
    freeze(db)
    today=today or datetime.now(timezone.utc).date().isoformat()
    if today<TRADE_DATE:return dict(status='pending_open',trade_date=TRADE_DATE,positions=list(EXPECTED))
    entry=rows_on(db,TRADE_DATE)
    if not all(entry[t] and positive(entry[t].get('open')) for t in EXPECTED+(BENCHMARK,)):
        return dict(status='pending_open',reason='verified_exchange_open_prices_missing',
                    missing=[t for t in EXPECTED+(BENCHMARK,) if not entry[t] or not positive(entry[t].get('open'))])
    recorded=(db.table('research_pilot_positions').select('*').eq('pilot_id',PILOT_ID).execute().data or [])
    if not all(p.get('entry_open') is not None for p in recorded):
        if any(p.get('entry_open') is not None for p in recorded):
            raise RuntimeError('Partial entry ledger; manual integrity review required')
        for p in recorded:
            row=entry[p['ticker']]
            price=positive(row['open'])
            db.table('research_pilot_positions').update(
                dict(entry_open=price,entry_shares=USD_EACH/price,
                     entry_observed_at=row.get('captured_at') or datetime.now(timezone.utc).isoformat())
            ).eq('pilot_id',PILOT_ID).eq('company_id',p['company_id']).is_('entry_open','null').execute()
        db.table('research_pilots').update({'status':'simulated'}).eq('pilot_id',PILOT_ID).execute()
    # Backfill only completed, common market sessions. Never forward-fill a
    # missing ticker and never compute mixed-date portfolio returns.
    companies=(db.table('companies').select('id,ticker')
               .in_('ticker',list(EXPECTED+(BENCHMARK,))).execute().data or [])
    tickers={c['id']:c['ticker'] for c in companies}
    if set(tickers.values())!=set(EXPECTED+(BENCHMARK,)):
        raise RuntimeError('Benchmark or pilot ticker is missing')
    historical=(db.table('price_history').select('company_id,price_date,close,captured_at')
                .in_('company_id',list(tickers)).gte('price_date',TRADE_DATE)
                .lte('price_date',today).order('price_date').execute().data or [])
    by_day={}
    for row in historical:
        ticker=tickers.get(row['company_id'])
        close=positive(row.get('close'))
        if ticker and close:
            by_day.setdefault(row['price_date'],{}).setdefault(ticker,close)
    complete={day:values for day,values in by_day.items()
              if len(values)==len(EXPECTED)+1}
    for day,values in sorted(complete.items()):
        db.table('research_pilot_marks').upsert([
            dict(pilot_id=PILOT_ID,price_date=day,ticker=t,close=values[t])
            for t in EXPECTED+(BENCHMARK,)
        ],on_conflict='pilot_id,price_date,ticker',ignore_duplicates=True).execute()
    marks=(db.table('research_pilot_marks').select('ticker,close,price_date')
           .eq('pilot_id',PILOT_ID).gte('price_date',TRADE_DATE)
           .order('price_date',desc=True).execute().data or [])
    saved_days={}
    for row in marks:
        saved_days.setdefault(row['price_date'],{})[row['ticker']]=positive(row['close'])
    full_days={day:values for day,values in saved_days.items()
               if len(values)==6 and all(values.get(t) for t in EXPECTED+(BENCHMARK,))}
    if not full_days:
        raise RuntimeError('Pilot data incomplete: no common close for all five picks and SPY')
    asof=max(full_days)
    latest=full_days[asof]
    positions=(db.table('research_pilot_positions').select('ticker,entry_open,entry_shares')
               .eq('pilot_id',PILOT_ID).execute().data or [])
    if len(positions)!=5 or any(not positive(p.get('entry_open')) or
                                not positive(p.get('entry_shares')) for p in positions):
        raise RuntimeError('Pilot entries are incomplete')
    benchmark_entry=positive(entry[BENCHMARK]['open'])
    totals=[dict(ticker=p['ticker'],entry_open=p['entry_open'],shares=p['entry_shares'],
                 latest_close=latest[p['ticker']],
                 pnl_usd=float(p['entry_shares'])*(latest[p['ticker']]-float(p['entry_open'])))
            for p in positions]
    return dict(status='simulated',trade_date=TRADE_DATE,asof=asof,
                observed_complete_sessions=len(full_days),
                data_lag=asof<max(by_day) if by_day else False,
                missing_latest_tickers=sorted(set(EXPECTED+(BENCHMARK,))-
                  set(by_day.get(max(by_day),{}))) if by_day else list(EXPECTED+(BENCHMARK,)),
                assumed_gross_pnl_usd=sum(p['pnl_usd'] for p in totals),
                benchmark_gross_pnl_usd=5000*(latest[BENCHMARK]/benchmark_entry-1),
                positions=totals,limitations=['Assumed open, not actual broker fills',
                'Commissions, bid/ask spread, FX, dividends and taxes excluded'])

if __name__=='__main__':
    print(json.dumps(update(get_supabase()),indent=2))
