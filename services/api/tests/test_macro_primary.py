import asyncio
import httpx
import pytest
from app.providers.macro import MacroProvider
from app.providers.macro_primary import BLS,bls_rows,treasury_rows,fed_rows

NOW='2026-10-10T16:00:00Z'
XML=b'''<feed xmlns:m="metadata" xmlns:d="data"><m:properties><d:NEW_DATE>2026-10-09T00:00:00</d:NEW_DATE><d:BC_2YEAR>4.1</d:BC_2YEAR><d:BC_10YEAR>4.3</d:BC_10YEAR></m:properties><m:properties><d:NEW_DATE>2026-10-11T00:00:00</d:NEW_DATE><d:BC_2YEAR>9</d:BC_2YEAR></m:properties></feed>'''


def test_agency_parsers_preserve_units_and_do_not_invent_vintages():
    rows=treasury_rows('DGS2',XML,NOW,'percent','https://home.treasury.gov/test')
    assert len(rows)==1 and rows[0]['value']==4.1 and rows[0]['vintage_date'] is None and rows[0]['observed_at']==NOW
    data={'status':'REQUEST_SUCCEEDED','Results':{'series':[{'seriesID':BLS['CPIAUCSL'],'data':[
        {'year':'2026','period':'M09','value':'328.2'},{'year':'2026','period':'M13','value':'999'}]}]}}
    rows=bls_rows('CPIAUCSL',data,NOW,'index')
    assert len(rows)==1 and rows[0]['observation_date']=='2026-09-01' and rows[0]['units']=='index'
    assert bls_rows('UNRATE',data,NOW,'percent')==[]
    assert fed_rows({'refRates':[{'type':'SOFR','effectiveDate':'2026-10-09','percentRate':4}]},NOW,'percent')==[]
    with pytest.raises(ValueError):bls_rows('CPIAUCSL',{'status':'REQUEST_NOT_PROCESSED'},NOW,'index')


def test_fred_outage_uses_originating_agencies_and_reuses_bulk_downloads(monkeypatch):
    monkeypatch.delenv('FRED_API_KEY',raising=False)
    requests=[]
    def respond(request):
        requests.append(request)
        if request.url.host=='fred.stlouisfed.org':raise httpx.ReadTimeout('unavailable',request=request)
        if request.url.host=='markets.newyorkfed.org':
            return httpx.Response(200,json={'refRates':[{'type':'EFFR','effectiveDate':'2026-10-09','percentRate':3.63}]})
        if request.url.host=='home.treasury.gov':return httpx.Response(200,content=XML)
        if request.url.host=='api.bls.gov':
            return httpx.Response(200,json={'status':'REQUEST_SUCCEEDED','Results':{'series':[
                {'seriesID':s,'data':[{'year':'2026','period':'M09','value':'10'}]} for s in BLS.values()]}})
        raise AssertionError(request.url)
    async def run():
        provider=MacroProvider()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            rows=[await provider.observations(client,s,NOW) for s in ('DFF','DGS2','DGS10','CPIAUCSL','UNRATE','PAYEMS')]
            with pytest.raises(ValueError):await provider.observations(client,'GDPC1',NOW)
            return rows
    rows=asyncio.run(run())
    assert len(requests)==4 and all(r and r[0]['vintage_date'] is None for r in rows)
    assert rows[0][0]['source']=='nyfed_current' and rows[1][0]['source']=='us_treasury_current' and rows[3][0]['source']=='bls_current'
