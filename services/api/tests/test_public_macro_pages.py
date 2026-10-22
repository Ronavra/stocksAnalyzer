import asyncio
import httpx
import pytest
from app.providers.public_macro_pages import dollar_rows,wti_rows,fred_page_rows,bls_html_events
from app.providers.macro import MacroProvider
NOW='2026-10-22T13:00:00Z'


def test_agency_tables_keep_dates_units_and_first_observation_not_vintage():
    dollar='<h5>Nominal Broad Dollar Index</h5><table><tr><td>20-OCT-26</td><td>120.3</td></tr><tr><td>29-OCT-26</td><td>130</td></tr></table>'
    rows=dollar_rows(dollar,NOW,'index')
    assert len(rows)==1 and rows[0]['value']==120.3 and rows[0]['vintage_date'] is None
    wti='<h1>Cushing WTI Spot Price</h1><table><tr><td>2026 Oct-19 to Oct-23</td><td>70</td><td></td><td>71</td><td>72</td><td>999</td></tr></table>'
    rows=wti_rows(wti,NOW,'USD per barrel')
    assert [r['observation_date'] for r in rows]==['2026-10-19','2026-10-21','2026-10-22']
    assert all(r['observed_at']==NOW for r in rows)
    gdp='<h1>GDPC1</h1><table><tr><th>Q2 2026:</th><td>24,408.011</td></tr></table>'
    assert fred_page_rows('GDPC1',gdp,NOW,'billions','https://fred.stlouisfed.org/series/GDPC1')[0]['value']==24408.011
    with pytest.raises(ValueError):fred_page_rows('GDPC1','<html>Access denied</html>',NOW,'billions','https://fred.stlouisfed.org')


def test_bls_timed_releases_only_and_daylight_saving_timezone():
    html='<table><tr><td>Friday, October 2, 2026</td><td>08:30 AM</td><td>Employment Situation</td></tr><tr><td>Monday, October 12, 2026</td><td></td><td>Holiday</td></tr></table>'
    rows=bls_html_events(html,NOW,'https://www.bls.gov/schedule/2026/10_sched_list.htm')
    assert len(rows)==1 and rows[0]['event_at']=='2026-10-02T08:30:00-04:00'


def test_one_csv_outage_does_not_skip_other_series_and_gdp_uses_public_table(monkeypatch):
    monkeypatch.delenv('FRED_API_KEY',raising=False);requests=[]
    def respond(request):
        requests.append(str(request.url))
        if request.url.path=='/graph.csv':return httpx.Response(403)
        if request.url.host=='markets.newyorkfed.org':return httpx.Response(200,json={'refRates':[{'type':'EFFR','effectiveDate':'2026-10-20','percentRate':3.6}]})
        if request.url.path=='/series/GDPC1':return httpx.Response(200,text='<h1>GDPC1</h1><table><tr><td>Q2 2026:</td><td>24408.011</td></tr></table>')
        raise AssertionError(request.url)
    async def run():
        p=MacroProvider()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as c:
            await p.observations(c,'DFF',NOW)
            return await p.observations(c,'GDPC1',NOW)
    rows=asyncio.run(run())
    assert sum('/graph.csv' in r for r in requests)==2 and rows[0]['source']=='fred_current_html'
