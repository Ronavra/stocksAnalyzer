"""Parse bounded, retryable Form 4 batches from verified SEC issuer filings."""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from urllib.parse import urlparse
import httpx
from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR)); load_dotenv(API_DIR / '.env')
from app.db.client import get_supabase
from app.providers.sec import SECProvider
from app.research.evidence import insider_transactions,ownership_target,ownership_issuer
from app.research.collection import now, start, finish, check, save_events


async def refresh(db, provider, limit=500,retry_errors_only=False):
    run = start(db, 'insider_transactions_refresh')
    report = {'attempted': 0, 'transactions': 0, 'errors': [], 'bounded_batch': True}
    try:
        companies = {x['id']: x for x in db.table('companies').select('id,ticker,cik').eq('active', True).eq('is_sp500', True).execute().data or []}
        query = db.table('company_disclosures').select('*').in_('form', ['4','4/A'])
        query=query.eq('ownership_status','error') if retry_errors_only else query.or_('ownership_parsed_at.is.null,ownership_status.eq.error')
        events=query.gte('filing_date', (datetime.now(timezone.utc)-timedelta(days=90)).date().isoformat()).order('published_at', desc=True).limit(max(1,min(limit,1000))).execute().data or []
        async with httpx.AsyncClient(timeout=45, headers={'User-Agent': provider.user_agent}) as client:
            for event in events:
                c = companies.get(event['company_id'])
                if not c: continue
                report['attempted'] += 1
                try:
                    parsed = urlparse(event['source_url'])
                    if parsed.scheme != 'https' or parsed.hostname != 'www.sec.gov' or not parsed.path.startswith('/Archives/edgar/data/'):
                        raise ValueError('Expected an official ownership XML URL')
                    parts = [p for p in parsed.path.split('/') if not p.startswith('xsl')]
                    url = 'https://www.sec.gov' + '/'.join(parts)
                    response = await client.get(url); response.raise_for_status()
                    if len(response.content) > 5_000_000: raise ValueError('Ownership XML exceeds limit')
                    target=ownership_target(response.content,c,companies.values())
                    rows = insider_transactions(response.content, target, event, now()) if target else []
                except Exception as exc:
                    known_reasons={
                        'Ownership filing issuer identity mismatch':'issuer_mismatch',
                        'Ownership transaction is in the future':'future_transaction',
                        'Expected an official ownership XML URL':'invalid_source_url',
                        'Ownership XML exceeds limit':'size_limit',
                    }
                    reason=known_reasons.get(str(exc),'source_or_parse_error')
                    report['errors'].append({'ticker': c['ticker'], 'type': type(exc).__name__,'reason':reason,'accession':event['accession_number']})
                    db.table('company_disclosures').update({'ownership_status':'error'}).eq('id', event['id']).execute()
                    check(db, 'ownership', 'sec_form4', 'error', c['id'], accession=event['accession_number'], error_type=type(exc).__name__,reason=reason)
                    if len(report['errors']) >= 10: break
                    continue
                # Storage errors are not mistaken for provider data gaps.
                save_events(db, rows)
                report['transactions'] += len(rows)
                db.table('company_disclosures').update({'ownership_status':'parsed','ownership_parsed_at':now()}).eq('id',event['id']).execute()
                check(db, 'ownership', 'sec_form4', 'success', c['id'], transactions=len(rows) if target and target['id']==c['id'] else 0, accession=event['accession_number'], institutional_holdings_collected=False,issuer_cik=ownership_issuer(response.content),issuer_company_id=target['id'] if target else None,reporting_owner_inventory=target is None or target['id']!=c['id'])
                if target and target['id']!=c['id']:
                    check(db,'ownership','sec_form4','success',target['id'],transactions=len(rows),accession=event['accession_number'],routed_from_reporting_owner=c['ticker'],institutional_holdings_collected=False)
                await asyncio.sleep(.2)
        report['batch_limit'] = limit
        return finish(db, run, report)
    except Exception as exc:
        report['errors'].append({'type':type(exc).__name__}); finish(db,run,report); raise


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--limit',type=int,default=500);parser.add_argument('--retry-errors-only',action='store_true'); args=parser.parse_args()
    if asyncio.run(refresh(get_supabase(),SECProvider(),args.limit,args.retry_errors_only)) != 'success': sys.exit(1)
