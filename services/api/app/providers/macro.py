"""Official macro observations: current CSV captures or dated ALFRED vintages."""
import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
import os
from zoneinfo import ZoneInfo
import httpx
from app.research.evidence import number, fingerprint
from app.providers.macro_primary import primary_observations

SERIES = {
 'DFF': ('Federal funds rate','percent',7),
 'DGS2': ('2-year Treasury yield','percent',7),
 'DGS10': ('10-year Treasury yield','percent',7),
 'CPIAUCSL': ('Consumer price index','index',75),
 'UNRATE': ('Unemployment rate','percent',75),
 'PAYEMS': ('Nonfarm payrolls','thousands of persons',75),
 'GDPC1': ('Real GDP','billions of chained dollars; source base',150),
 'DTWEXBGS': ('Broad dollar index','index',10),
 'DCOILWTICO': ('WTI crude oil','USD per barrel',10),
}


def csv_observations(series, text, observed_at):
    rows=[]
    for item in csv.DictReader(StringIO(text)):
        when=item.get('observation_date') or item.get('DATE')
        value=number(item.get(series))
        if not when or value is None: continue
        datetime.fromisoformat(when)
        if when>observed_at[:10]: continue
        payload={'value':value,'vintage_date':None}
        rows.append({'series_id':series,'observation_date':when,'value':value,'units':SERIES[series][1],
                     'source':'fred_current_csv','vintage_date':None,'observed_at':observed_at,
                     'source_url':f'https://fred.stlouisfed.org/series/{series}','fingerprint':fingerprint(payload)})
    if not rows: raise ValueError('FRED CSV contains no observations')
    return rows


def vintage_observations(series, items, observed_at):
    rows=[]
    for item in items:
        value=number(item.get('value')); when=item.get('date'); vintage=item.get('realtime_start')
        if value is None or not when or not vintage: continue
        datetime.fromisoformat(when); datetime.fromisoformat(vintage)
        if when>observed_at[:10] or vintage>observed_at[:10]: continue
        rows.append({'series_id':series,'observation_date':when,'value':value,'units':SERIES[series][1],
                     'source':'alfred_vintage','vintage_date':vintage,'observed_at':observed_at,
                     'source_url':f'https://fred.stlouisfed.org/series/{series}',
                     'fingerprint':fingerprint({'value':value,'vintage_date':vintage})})
    return rows


class MacroProvider:
    def __init__(self, api_key=None):
        self.api_key=api_key or os.getenv('FRED_API_KEY')
        self.primary_cache={};self.csv_unavailable=False

    async def observations(self, client, series, observed_at):
        if self.csv_unavailable:
            return await primary_observations(client,series,observed_at,SERIES[series][1],self.primary_cache)
        try:
            return await self.fred_observations(client,series,observed_at)
        except httpx.HTTPError:
            if not self.api_key:self.csv_unavailable=True
            return await primary_observations(client,series,observed_at,SERIES[series][1],self.primary_cache)

    async def fred_observations(self, client, series, observed_at):
        end=observed_at[:10]
        since=(datetime.fromisoformat(observed_at.replace('Z','+00:00'))-timedelta(days=370)).date().isoformat()
        if not self.api_key:
            response=await client.get('https://fred.stlouisfed.org/graph.csv',params={'id':series,'cosd':since,'coed':end},timeout=15)
            response.raise_for_status()
            if len(response.content)>5_000_000: raise ValueError('Macro CSV exceeds limit')
            return csv_observations(series,response.text,observed_at)
        rows=[]; offset=0
        for _ in range(20):
            response=await client.get('https://api.stlouisfed.org/fred/series/observations',params={
                'api_key':self.api_key,'file_type':'json','series_id':series,'observation_start':since,
                'observation_end':end,'realtime_start':'1776-07-04','realtime_end':end,'limit':10000,'offset':offset,'output_type':1})
            response.raise_for_status(); data=response.json()
            if not isinstance(data.get('observations'),list): raise ValueError('Missing ALFRED observations')
            rows.extend(vintage_observations(series,data['observations'],observed_at))
            offset+=len(data['observations'])
            if offset>=int(data.get('count',offset)): return rows
            if not data['observations']: raise ValueError('ALFRED pagination stalled')
        raise ValueError('ALFRED batch exceeds bounded vintage limit')


def bls_calendar(text, observed_at):
    # RFC5545 folded lines are continuations; preserve UID across schedule revisions.
    text=text.replace('\r\n','\n').replace('\n ','').replace('\n\t','')
    events=[]; item=None
    for line in text.splitlines():
        if line=='BEGIN:VEVENT': item={}; continue
        if line=='END:VEVENT' and item is not None:
            title=item.get('SUMMARY'); stamp=item.get('DTSTART'); uid=item.get('UID')
            if title and stamp and uid:
                if stamp.endswith('Z'):
                    when=datetime.strptime(stamp,'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
                else:
                    when=datetime.strptime(stamp,'%Y%m%dT%H%M%S').replace(tzinfo=ZoneInfo(item.get('TZ','America/New_York')))
                payload={'title':title,'event_at':when.isoformat()}
                events.append({'source':'bls','source_record_id':uid,'source_url':'https://www.bls.gov/schedule/news_release/bls.ics',
                               'title':title,'event_at':when.isoformat(),'observed_at':observed_at,'fingerprint':fingerprint(payload)})
            item=None; continue
        if item is not None and ':' in line:
            key,value=line.split(':',1); base=key.split(';')[0]
            item[base]=value.replace('\\,',',').replace('\\n',' ')
            if base=='DTSTART' and 'TZID=' in key: item['TZ']=key.split('TZID=',1)[1].split(';')[0]
    if not events: raise ValueError('BLS calendar contains no timed releases')
    return events
