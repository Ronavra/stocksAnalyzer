"""Current observations from originating public agencies; never vintage data."""
from datetime import date
import xml.etree.ElementTree as ET
from app.research.evidence import number,fingerprint

BLS={'CPIAUCSL':'CUSR0000SA0','UNRATE':'LNS14000000','PAYEMS':'CES0000000001'}
TREASURY_URL='https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml'
BLS_URL='https://api.bls.gov/publicAPI/v1/timeseries/data/'
FED_URL='https://markets.newyorkfed.org/api/rates/unsecured/effr/last/200.json'


def current_observation(series,when,value,source,url,observed_at,units):
    value=number(value)
    if value is None:return None
    date.fromisoformat(when)
    if when>observed_at[:10]:return None
    return {'series_id':series,'observation_date':when,'value':value,'units':units,
            'source':source,'source_url':url,'vintage_date':None,'observed_at':observed_at,
            'fingerprint':fingerprint({'value':value,'vintage_date':None})}


def treasury_rows(series,xml,observed_at,units,url):
    field={'DGS2':'BC_2YEAR','DGS10':'BC_10YEAR'}[series];rows=[]
    root=ET.fromstring(xml)
    for node in root.iter():
        if node.tag.split('}')[-1]!='properties':continue
        item={x.tag.split('}')[-1]:x.text for x in node}
        when=(item.get('NEW_DATE') or '')[:10]
        if not when:continue
        row=current_observation(series,when,item.get(field),'us_treasury_current',url,observed_at,units)
        if row:rows.append(row)
    return rows


def bls_rows(series,data,observed_at,units):
    if data.get('status')!='REQUEST_SUCCEEDED':raise ValueError('BLS public observations unavailable')
    results=data.get('Results') or {}
    if isinstance(results,list):results=results[0] if results else {}
    rows=[]
    for item in results.get('series',[]):
        if item.get('seriesID')!=BLS[series]:continue
        for value in item.get('data',[]):
            period=value.get('period','')
            if len(period)!=3 or not period.startswith('M') or not period[1:].isdigit() or not 1<=int(period[1:])<=12:continue
            when=f"{value['year']}-{period[1:]}-01"
            row=current_observation(series,when,value.get('value'),'bls_current',BLS_URL,observed_at,units)
            if row:rows.append(row)
    return rows


def fed_rows(data,observed_at,units):
    rows=[]
    for value in data.get('refRates',[]):
        if value.get('type') not in (None,'EFFR'):continue
        when=value.get('effectiveDate')
        if not when:continue
        row=current_observation('DFF',when,value.get('percentRate'),'nyfed_current',FED_URL,observed_at,units)
        if row:rows.append(row)
    return rows


async def primary_observations(client,series,observed_at,units,cache):
    if series in ('DGS2','DGS10'):
        year=observed_at[:4];key='treasury:'+year
        if key not in cache:
            response=await client.get(TREASURY_URL,params={'data':'daily_treasury_yield_curve','field_tdr_date_value':year},timeout=20)
            response.raise_for_status()
            if len(response.content)>5_000_000:raise ValueError('Treasury XML exceeds limit')
            cache[key]=(response.content,str(response.url))
        xml,url=cache[key];rows=treasury_rows(series,xml,observed_at,units,url)
    elif series in BLS:
        if 'bls' not in cache:
            response=await client.post(BLS_URL,json={'seriesid':list(BLS.values()),'startyear':str(int(observed_at[:4])-1),'endyear':observed_at[:4]},timeout=20)
            response.raise_for_status()
            if len(response.content)>5_000_000:raise ValueError('BLS JSON exceeds limit')
            cache['bls']=response.json()
        rows=bls_rows(series,cache['bls'],observed_at,units)
    elif series=='DFF':
        response=await client.get(FED_URL,timeout=20);response.raise_for_status()
        if len(response.content)>5_000_000:raise ValueError('NY Fed JSON exceeds limit')
        rows=fed_rows(response.json(),observed_at,units)
    else:raise ValueError('No originating-agency fallback for this macro series')
    if not rows:raise ValueError('Originating agency returned no numeric observations')
    return rows
