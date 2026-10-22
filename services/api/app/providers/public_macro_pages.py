"""Bounded public-agency tables. Current captures never become historical vintages."""
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
import re
from zoneinfo import ZoneInfo
from .macro_primary import current_observation
from app.research.evidence import fingerprint

FED_DOLLAR='https://www.federalreserve.gov/releases/h10/summary/jrxwtfb_nb.htm'
EIA_WTI='https://www.eia.gov/dnav/pet/hist/RWTCd.htm'


class TableRows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        if tag in ('td','th') and self.row is not None:self.cell=[]
        if tag=='br' and self.cell is not None:self.cell.append(' ')
    def handle_data(self,text):
        if self.cell is not None:self.cell.append(text)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(re.sub(r'\s+',' ',''.join(self.cell)).strip());self.cell=None
        if tag=='tr' and self.row is not None:
            self.rows.append(self.row);self.row=None;self.cell=None


def table_rows(text):
    parser=TableRows();parser.feed(text);return parser.rows


def fred_page_rows(series,text,observed_at,units,url):
    if series not in text:raise ValueError('FRED series identity missing from page')
    rows=[]
    for cells in table_rows(text):
        if len(cells)<2:continue
        label=cells[0].strip(': ')
        try:
            quarter=re.fullmatch(r'Q([1-4])\s+(\d{4})',label)
            day=date(int(quarter[2]),1+3*(int(quarter[1])-1),1).isoformat() if quarter else date.fromisoformat(label).isoformat()
        except ValueError:continue
        value=cells[1].replace(',','').strip()
        row=current_observation(series,day,value,'fred_current_html',url,observed_at,units)
        if row:rows.append(row)
    if not rows:raise ValueError('FRED page has no dated observations')
    return rows


def dollar_rows(text,observed_at,units):
    if 'Broad Dollar Index' not in text:raise ValueError('Dollar series identity missing')
    rows=[];cutoff=(date.fromisoformat(observed_at[:10])-timedelta(days=370)).isoformat()
    for cells in table_rows(text):
        if len(cells)!=2:continue
        try:day=datetime.strptime(cells[0],'%d-%b-%y').date().isoformat()
        except ValueError:continue
        if day<cutoff:continue
        row=current_observation('DTWEXBGS',day,cells[1],'federal_reserve_current',FED_DOLLAR,observed_at,units)
        if row:rows.append(row)
    if not rows:raise ValueError('Dollar page has no dated observations')
    return rows


def wti_rows(text,observed_at,units):
    if 'WTI Spot Price' not in text:raise ValueError('WTI series identity missing')
    rows=[];cutoff=(date.fromisoformat(observed_at[:10])-timedelta(days=370)).isoformat()
    for cells in table_rows(text):
        if len(cells)!=6:continue
        match=re.fullmatch(r'(\d{4})\s+([A-Za-z]{3})-\s*(\d{1,2})\s+to\s+[A-Za-z]{3}-\s*\d{1,2}',cells[0])
        if not match:continue
        monday=datetime.strptime(f'{match[1]} {match[2]} {match[3]}','%Y %b %d').date()
        if monday.weekday()!=0:raise ValueError('WTI week label is not Monday')
        for offset,value in enumerate(cells[1:]):
            day=(monday+timedelta(days=offset)).isoformat()
            if day<cutoff:continue
            row=current_observation('DCOILWTICO',day,value,'eia_current',EIA_WTI,observed_at,units)
            if row:rows.append(row)
    if not rows:raise ValueError('WTI page has no dated observations')
    return rows


def bls_html_events(text,observed_at,url):
    events=[]
    for cells in table_rows(text):
        if len(cells)<3:continue
        try:day=datetime.strptime(cells[0],'%A, %B %d, %Y').date()
        except ValueError:continue
        try:clock=datetime.strptime(cells[1],'%I:%M %p').time()
        except ValueError:continue # Holidays and untimed notices are not release times.
        title=cells[2].strip()
        if not title:continue
        stamp=datetime.combine(day,clock,ZoneInfo('America/New_York')).isoformat()
        payload={'title':title,'event_at':stamp}
        events.append(dict(source='bls',source_record_id=f'{day}:{title}',source_url=url,title=title,
                           event_at=stamp,observed_at=observed_at,fingerprint=fingerprint(payload)))
    if not events:raise ValueError('BLS page has no timed release rows')
    return events


async def get_page(client,url):
    response=await client.get(url,timeout=20,follow_redirects=True)
    response.raise_for_status()
    if len(response.content)>5_000_000:raise ValueError('Public macro page exceeds limit')
    return response.text


async def page_observations(client,series,observed_at,units):
    if series=='DTWEXBGS':return dollar_rows(await get_page(client,FED_DOLLAR),observed_at,units)
    if series=='DCOILWTICO':return wti_rows(await get_page(client,EIA_WTI),observed_at,units)
    if series=='GDPC1':
        from .bea_public import observations
        try:return await observations(client,observed_at)
        except Exception:pass
    url=f'https://fred.stlouisfed.org/series/{series}'
    return fred_page_rows(series,await get_page(client,url),observed_at,units,url)


async def calendar_fallback(client,observed_at):
    day=date.fromisoformat(observed_at[:10]);rows=[];failures=[]
    for month in (day.replace(day=1),(day.replace(day=28)+timedelta(days=4)).replace(day=1)):
        url=f'https://www.bls.gov/schedule/{month.year}/{month.month:02d}_sched_list.htm'
        try:rows.extend(bls_html_events(await get_page(client,url),observed_at,url))
        except Exception as exc:failures.append(type(exc).__name__)
    if not rows:
        for month in (day.replace(day=1),(day.replace(day=28)+timedelta(days=4)).replace(day=1)):
            url=f'https://www.newyorkfed.org/research/calendars/i-{month.strftime("%b%y").lower()}.html'
            try:rows.extend(nyfed_calendar_events(await get_page(client,url),observed_at,url,month))
            except Exception as exc:failures.append(type(exc).__name__)
    if not rows:raise ValueError('Official economic calendars unavailable')
    return rows,failures


def nyfed_calendar_events(text,observed_at,url,month):
    from app.research.guidance import release_text
    label=month.strftime('%B')+r'\s*'+str(month.year)
    if not re.search(label,release_text(text),re.I):raise ValueError('NY Fed calendar month mismatch')
    result=[]
    for row in table_rows(text):
        for cell in row:
            match=re.match(r'^(\d{1,2})\s*(?=[A-Za-z])',cell)
            if not match:continue
            day=date(month.year,month.month,int(match[1]))
            for title,clock in re.findall(r'(.+?)\((\d{2}:\d{2})\)',cell[match.end():]):
                title=title.strip()
                if not title:continue
                stamp=datetime.combine(day,datetime.strptime(clock,'%H:%M').time(),ZoneInfo('America/New_York')).isoformat()
                payload={'title':title,'event_at':stamp}
                result.append(dict(source='nyfed_calendar',source_record_id=f'{day}:{title}',source_url=url,
                    title=title,event_at=stamp,observed_at=observed_at,fingerprint=fingerprint(payload)))
    if not result:raise ValueError('NY Fed calendar has no timed events')
    return result
