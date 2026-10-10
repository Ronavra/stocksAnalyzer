"""Archive SEC release text and explicitly registered issuer transcripts/slides."""
import argparse
import asyncio
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys
import httpx
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR));load_dotenv(API_DIR/'.env')
from app.db.client import get_supabase
from app.providers.sec import SECProvider
from app.providers.sec_documents import release_documents
from app.providers.investor_relations import registry,download,document_text,discovered_links
from app.research.evidence import document,evidence_event
from app.research.collection import now,start,finish,check,save_documents,save_events


async def refresh(db,provider,limit=100):
    run=start(db,'official_documents_refresh')
    report={'sec_filings_checked':0,'documents':0,'ir_companies':0,'errors':[],'bounded_batch':True}
    try:
        companies={x['id']:x for x in db.table('companies').select('id,ticker').eq('is_sp500',True).eq('active',True).execute().data or []}
        events=db.table('company_disclosures').select('*').in_('form',['8-K','8-K/A','6-K','6-K/A']).or_('documents_collected_at.is.null,document_status.eq.error').gte('filing_date',(datetime.now(timezone.utc)-timedelta(days=90)).date().isoformat()).order('published_at',desc=True).limit(max(1,min(limit,500))).execute().data or []
        for event in events:
            if event['company_id'] not in companies:continue
            try:
                docs=await release_documents(provider,event)
                rows=[document(event['company_id'],url,html,now(),event['published_at'],event['accession_number']) for url,html in docs]
            except Exception as exc:
                report['errors'].append({'accession':event['accession_number'],'type':type(exc).__name__})
                db.table('company_disclosures').update({'document_status':'error'}).eq('id',event['id']).execute()
                if len(report['errors'])>=10: break
                continue
            save_documents(db,rows)
            items=event.get('items') or []
            if items:
                save_events(db,[evidence_event(event['company_id'],'material_event','sec',event['accession_number'],event['source_url'],{'form':event['form'],'items':items,'headline':event['headline']},now(),event['filing_date'],event['published_at'])])
            db.table('company_disclosures').update({'document_status':'archived','documents_collected_at':now()}).eq('id',event['id']).execute()
            report['sec_filings_checked']+=1;report['documents']+=len(rows)
            await asyncio.sleep(.2)
        by_ticker={x['ticker']:x for x in companies.values()}
        for ticker,entry in registry().items():
            if ticker not in by_ticker:continue
            c=by_ticker[ticker];targets=list(entry.get('documents',[]));errors=[]
            async with httpx.AsyncClient(timeout=60,headers={'User-Agent':provider.user_agent}) as client:
                for url in entry.get('pages',[]):
                    try:
                        final,raw,ctype=await download(client,url,entry['hosts'])
                        html=document_text(raw,ctype,final)
                        targets.extend(discovered_links(final,html,entry['hosts']))
                    except Exception as exc: errors.append({'type':type(exc).__name__,'stage':'index'})
                seen=set();count=0;call_count=0
                for target in targets[:15]:
                    if target['url'] in seen:continue
                    seen.add(target['url'])
                    try:
                        final,raw,ctype=await download(client,target['url'],entry['hosts'])
                        html=document_text(raw,ctype,final)
                        row=document(c['id'],final,html,now(),target.get('published_at'),kind=target['kind'])
                    except Exception as exc: errors.append({'type':type(exc).__name__,'stage':'document'});continue
                    save_documents(db,[row]);count+=1
                    call_count+=row['kind'] in ('transcript','presentation')
                report['documents']+=count;report['ir_companies']+=1
                check(db,'calls','company_ir','partial' if errors else 'success',c['id'],documents=count,call_documents=call_count,errors=errors,registry_limited=True)
                report['errors'].extend({'ticker':ticker,**e} for e in errors)
        report['ir_registry_companies']=len(registry());report['unregistered_ir_companies']=len(companies)-len(set(registry())&set(by_ticker))
        return finish(db,run,report)
    except Exception as exc:
        report['errors'].append({'type':type(exc).__name__});finish(db,run,report);raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=100);args=parser.parse_args()
    if asyncio.run(refresh(get_supabase(),SECProvider(),args.limit))!='success':sys.exit(1)
