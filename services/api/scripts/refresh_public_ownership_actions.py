"""Current public holding observations and historical actions; never backdated."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import time
import yfinance as yf
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR));load_dotenv(API_DIR/'.env')
from app.db.client import get_supabase
from app.research.evidence import evidence_event,number
from app.research.collection import now,start,finish,save_events
from app.research.prospective_metrics import paged


def holding_rows(company_id,frame,observed_at,ticker=None):
    rows=[]
    if frame is None or frame.empty:return rows
    for item in frame.to_dict('records'):
        holder=item.get('Holder');stamp=item.get('Date Reported')
        if not holder or stamp is None:continue
        when=stamp.date().isoformat() if hasattr(stamp,'date') else str(stamp)[:10]
        try:datetime.fromisoformat(when)
        except ValueError:continue
        if when>observed_at[:10]:continue
        payload={'holder':str(holder),'reported_date':when,'shares':number(item.get('Shares')),
                 'reported_value':number(item.get('Value')),'reported_fraction_held':number(item.get('pctHeld')),
                 'reported_fraction_change':number(item.get('pctChange')),
                 'original_filing_verified':False,'filer_cik':None,'currency':None}
        if payload['shares'] is None:continue
        rows.append(evidence_event(company_id,'institutional_holding','yahoo_institutional_holders',f'{holder}:{when}',
                                   f'https://finance.yahoo.com/quote/{ticker}/holders/' if ticker else 'https://finance.yahoo.com',payload,observed_at,when))
    return rows


def action_rows(company_id,frame,observed_at,ticker):
    rows=[]
    if frame is None or frame.empty:return rows
    for stamp,item in frame.iterrows():
        when=stamp.date().isoformat()
        if when>observed_at[:10]:continue
        for column,kind in [('Dividends','dividend'),('Stock Splits','split')]:
            value=number(item.get(column))
            if value is None or value<=0:continue
            payload={'amount' if kind=='dividend' else 'ratio':value,'currency':None,'date':when,'scope':'historical_only'}
            rows.append(evidence_event(company_id,kind,'yahoo_actions',when,f'https://finance.yahoo.com/quote/{ticker}/history/',payload,observed_at,when))
    return rows


def refresh(db,limit=None,delay=.3):
    run=start(db,'public_ownership_actions_refresh');today=now()[:10]
    report={'checked':0,'reused_checks':0,'holdings':0,'actions':0,'errors':[],'empty_holdings':[],'upcoming_actions_collected':False,'original_13f_filings_verified':False}
    try:
        companies=db.table('companies').select('id,ticker').eq('active',True).eq('is_sp500',True).order('ticker').execute().data or []
        prior=paged(db.table('research_collection_checks').select('id,company_id,source').in_('source',['yahoo_institutional_holders','yahoo_actions']).eq('status','success').gte('checked_at',today+'T00:00:00Z').order('id'))
        done={(x['company_id'],x['source']) for x in prior};attempted=0;checks=[]
        for c in companies:
            sources=[s for s in ['yahoo_institutional_holders','yahoo_actions'] if (c['id'],s) not in done]
            report['reused_checks']+=2-len(sources)
            if not sources:continue
            if limit is not None and attempted>=limit:break
            attempted+=1;ticker=yf.Ticker(c['ticker'])
            for source in sources:
                try:
                    if source=='yahoo_institutional_holders':
                        frame=ticker.get_institutional_holders();rows=holding_rows(c['id'],frame,now(),c['ticker']);family='ownership'
                    else:
                        frame=ticker.history(period='2y',auto_adjust=False,actions=True,raise_errors=True)
                        rows=action_rows(c['id'],frame,now(),c['ticker']);family='actions'
                        if frame is None or frame.empty:raise ValueError('No action history response')
                except Exception as exc:
                    report['errors'].append({'ticker':c['ticker'],'source':source,'type':type(exc).__name__})
                    checks.append({'company_id':c['id'],'family':'ownership' if source=='yahoo_institutional_holders' else 'actions','source':source,'status':'error','checked_at':now(),'metadata':{'error_type':type(exc).__name__}})
                    continue
                save_events(db,rows)
                report['holdings' if family=='ownership' else 'actions']+=len(rows)
                if family=='ownership' and not rows:report['empty_holdings'].append(c['ticker'])
                checks.append({'company_id':c['id'],'family':family,'source':source,'status':'success','checked_at':now(),
                               'metadata':{'events':len(rows),'original_filing_verified':False,'upcoming_actions_collected':False}})
            report['checked']+=1
            if len(checks)>=50:
                db.table('research_collection_checks').insert(checks,returning='minimal').execute();checks=[]
                print(f"Public ownership/action checks: {report['checked']}/{len(companies)}",flush=True)
            if len(report['errors'])>=20:break
            time.sleep(delay)
        if checks:db.table('research_collection_checks').insert(checks,returning='minimal').execute()
        report['universe']=len(companies);report['bounded_limit']=limit
        return finish(db,run,report)
    except Exception as exc:
        report['errors'].append({'type':type(exc).__name__});finish(db,run,report);raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int);args=parser.parse_args()
    if refresh(get_supabase(),args.limit)!='success':sys.exit(1)
