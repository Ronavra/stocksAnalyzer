import asyncio
from datetime import datetime
from io import BytesIO
import httpx
import pandas as pd
import pytest
from pypdf import PdfWriter
from app.research.evidence import document,insider_transactions,corporate_actions,fingerprint,ownership_target
from app.providers.macro import csv_observations,vintage_observations,bls_calendar,MacroProvider
from app.providers.investor_relations import download,discovered_links,document_text
from scripts.refresh_public_ownership_actions import holding_rows,action_rows

NOW='2026-10-10T15:00:00Z'


def test_reporting_owner_inventory_routes_only_to_verified_unique_issuer():
    xml=b'<ownershipDocument><issuer><issuerCik>0002000</issuerCik></issuer></ownershipDocument>'
    owner={'id':1,'cik':'1000'};issuer={'id':2,'cik':'2000'}
    assert ownership_target(xml,owner,[owner,issuer])==issuer
    assert ownership_target(xml,owner,[owner]) is None
    assert ownership_target(xml,issuer,[issuer,{'id':3,'cik':'2000'}])==issuer
    with pytest.raises(ValueError):ownership_target(xml,owner,[issuer,{'id':3,'cik':'2000'}])


def test_ownership_identity_joint_owners_and_derivatives_do_not_create_false_purchases():
    xml=b'''<ownershipDocument><issuer><issuerCik>1000</issuerCik></issuer>
    <reportingOwner><reportingOwnerId><rptOwnerName>A</rptOwnerName></reportingOwnerId></reportingOwner>
    <reportingOwner><reportingOwnerId><rptOwnerName>B</rptOwnerName></reportingOwnerId></reportingOwner>
    <nonDerivativeTable><nonDerivativeTransaction><transactionDate><value>2026-10-01</value></transactionDate><transactionCoding><transactionCode>P</transactionCode></transactionCoding><transactionAmounts><transactionShares><value>10</value></transactionShares><transactionPricePerShare><value>5</value></transactionPricePerShare></transactionAmounts></nonDerivativeTransaction></nonDerivativeTable>
    <derivativeTable><derivativeTransaction><transactionCoding><transactionCode>M</transactionCode></transactionCoding><transactionAmounts><transactionShares><value>20</value></transactionShares></transactionAmounts></derivativeTransaction></derivativeTable></ownershipDocument>'''
    event={'accession_number':'a','form':'4/A','source_url':'https://www.sec.gov/a.xml','published_at':'2026-10-02T12:00:00Z'}
    rows=insider_transactions(xml,{'id':1,'cik':'0001000'},event,NOW)
    assert len(rows)==2 and len(rows[0]['payload']['owners'])==2
    assert rows[0]['payload']['reported_value']==50 and rows[0]['payload']['purchase_or_private_purchase']
    assert rows[1]['payload']['reported_value'] is None and rows[1]['payload']['derivative'] and not rows[1]['payload']['purchase_or_private_purchase']
    assert rows[0]['payload']['amendment'] and rows[0]['observed_at']==NOW
    with pytest.raises(ValueError,match='identity'):insider_transactions(xml,{'id':1,'cik':'9999'},event,NOW)


def test_document_revisions_have_new_hash_without_backdating_collection():
    original=document(1,'https://www.sec.gov/a.htm','<p>Earnings release: conference call tomorrow.</p>',NOW,'2026-10-01T12:00:00Z','a')
    revised=document(1,original['source_url'],'<p>Corrected earnings release.</p>',NOW,'2026-10-01T12:00:00Z','a')
    assert original['kind']=='earnings_release' and original['content_hash']!=revised['content_hash']
    assert original['observed_at']==NOW and original['published_at']!=NOW
    assert document(1,'https://www.sec.gov/b.htm','<p>Appointment of a director</p>',NOW,accession='b')['kind']=='official_release'
    with pytest.raises(ValueError,match='future'):document(1,original['source_url'],'<p>Text</p>',NOW,'2026-10-11T12:00:00Z','a')


def test_current_macro_history_cannot_be_backdated_as_vintage_data():
    rows=csv_observations('DGS10','observation_date,DGS10\n2026-10-08,4.1\n2026-10-09,.\n2026-10-11,5.0\n',NOW)
    assert len(rows)==1 and rows[0]['vintage_date'] is None and rows[0]['observed_at']==NOW
    vintage=vintage_observations('DGS10',[{'date':'2026-10-08','value':'4.0','realtime_start':'2026-10-09'}],NOW)[0]
    assert vintage['vintage_date']=='2026-10-09' and vintage['observed_at']==NOW


def test_alfred_paginates_and_never_leaks_api_key_into_source_links():
    requests=[]
    def respond(request):
        requests.append(request)
        offset=int(request.url.params['offset'])
        return httpx.Response(200,json={'count':2,'observations':[{'date':'2026-10-08','value':str(4+offset),'realtime_start':f'2026-10-0{8+offset}'}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:return await MacroProvider('test-secret').observations(client,'DGS10',NOW)
    rows=asyncio.run(run())
    assert len(rows)==2 and [r.url.params['offset'] for r in requests]==['0','1']
    assert all('test-secret' not in r['source_url'] for r in rows)


def test_bls_calendar_keeps_release_timezone_and_schedule_revisions():
    text='BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:cpi\nSUMMARY:Consumer Price\n Index\nDTSTART;TZID=America/New_York:20261014T083000\nEND:VEVENT\nEND:VCALENDAR'
    event=bls_calendar(text,NOW)[0]
    assert event['title']=='Consumer PriceIndex' and event['event_at']=='2026-10-14T08:30:00-04:00'
    later=bls_calendar(text.replace('20261014','20261015'),NOW)[0]
    assert event['source_record_id']==later['source_record_id'] and event['fingerprint']!=later['fingerprint']


def test_ir_redirect_cannot_escape_issuer_allowlist():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(302,headers={'location':'https://unapproved.example/secret'}))) as client:
            return await download(client,'https://issuer.example/ir',{'issuer.example'})
    with pytest.raises(ValueError,match='allowlist'):asyncio.run(run())
    links=discovered_links('https://issuer.example/ir','<a href="/slides.pdf">Presentation</a><a href="https://evil.example/a">Transcript</a>',{'issuer.example'})
    assert links==[{'url':'https://issuer.example/slides.pdf','kind':'presentation'}]


def test_empty_pdf_is_unavailable_instead_of_false_complete_document():
    writer=PdfWriter();writer.add_blank_page(width=100,height=100);output=BytesIO();writer.write(output)
    with pytest.raises(ValueError,match='OCR'):document_text(output.getvalue(),'application/pdf','https://issuer.example/a.pdf')


def test_holding_report_date_is_distinct_from_current_observation():
    frame=pd.DataFrame([{'Holder':'Fund','Date Reported':datetime(2026,6,30),'Shares':100,'Value':500,'pctHeld':.01}])
    row=holding_rows(1,frame,NOW)[0]
    assert row['observed_at']==NOW and row['published_at'] is None and row['event_date']=='2026-06-30'
    assert not row['payload']['original_filing_verified']
    frame['Date Reported']=datetime(2026,10,11)
    assert holding_rows(1,frame,NOW)==[]


def test_historical_action_dates_are_not_publication_dates_and_zero_events_are_valid():
    frame=pd.DataFrame({'Dividends':[.5,0],'Stock Splits':[0,4]},index=pd.to_datetime(['2026-07-01','2026-08-01']))
    rows=action_rows(1,frame,NOW,'TEST')
    assert {r['kind'] for r in rows}=={'dividend','split'} and all(r['published_at'] is None and r['observed_at']==NOW for r in rows)
    assert corporate_actions(1,{'dividends':[]},'dividend',NOW)==[]
    assert fingerprint({'a':1,'b':2})==fingerprint({'b':2,'a':1})


def test_historical_sec_inventory_uses_only_verified_issuer_files(monkeypatch):
    from app.providers.sec import SECProvider
    submissions={'cik':1000,'filings':{'recent':{'accessionNumber':['new'],'form':['10-Q']},'files':[
        {'name':'CIK0000001000-submissions-001.json','filingFrom':'2023-01-01','filingTo':'2025-01-01'},
        {'name':'CIK0000001000-submissions-002.json','filingFrom':'2000-01-01','filingTo':'2001-01-01'}]}}
    original=httpx.AsyncClient
    monkeypatch.setattr('app.providers.sec.httpx.AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'accessionNumber':['old'],'form':['10-K'],'filingDate':['2024-01-01']})),**kwargs))
    result=asyncio.run(SECProvider('test').submission_history(1000,submissions,1825,NOW))
    recent=result['filings']['recent']
    assert recent['accessionNumber']==['new','old'] and recent['filingDate']==['','2024-01-01']
    assert submissions['filings']['recent']['accessionNumber']==['new']
    submissions['filings']['files'][0]['name']='CIK0000009999-submissions-001.json'
    with pytest.raises(ValueError,match='filename'):asyncio.run(SECProvider('test').submission_history(1000,submissions,1825,NOW))
