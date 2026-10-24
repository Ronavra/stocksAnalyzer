"""Real GDP levels from BEA's public national-accounts workbook, without an API key."""
from io import BytesIO
from zipfile import ZipFile,BadZipFile
import re
import posixpath
import xml.etree.ElementTree as ET
from .macro_primary import current_observation

URL='https://apps.bea.gov/national/Release/XLS/Survey/Section1All_xls.xlsx'
NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def cells(sheet,strings):
    rows=[]
    for row in sheet.findall('.//s:sheetData/s:row',NS):
        values={}
        for c in row.findall('s:c',NS):
            ref=re.match(r'[A-Z]+',c.get('r',''))
            if not ref:continue
            column=0
            for ch in ref[0]:column=column*26+ord(ch)-64
            v=c.findtext('s:v',namespaces=NS)
            if c.get('t')=='s':v=strings[int(v)] if v is not None else ''
            elif c.get('t')=='inlineStr':v=''.join(c.itertext())
            values[column]=v
        rows.append(values)
    return rows


def gdp_workbook(raw,observed_at):
    with ZipFile(BytesIO(raw)) as z:
        if sum(x.file_size for x in z.infolist())>120_000_000:raise ValueError('BEA workbook expanded size exceeds limit')
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            root=ET.fromstring(z.read('xl/sharedStrings.xml'))
            strings=[''.join(x.itertext()) for x in root]
        book=ET.fromstring(z.read('xl/workbook.xml'))
        rels=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        targets={r.get('Id'):r.get('Target') for r in rels}
        selected=None
        for sheet in book.findall('s:sheets/s:sheet',NS):
            name=sheet.get('name','')
            if name.lower() in ('t10106','t10106-q') or re.fullmatch(r'(?:table\s*)?1\.1\.6\.?',name,re.I):
                rid=sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                target=targets[rid]
                path=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
                if not path.startswith('xl/worksheets/'):raise ValueError('Unexpected BEA sheet target')
                selected=ET.fromstring(z.read(path));break
        if selected is None:raise ValueError('BEA real GDP table 1.1.6 missing')
        rows=cells(selected,strings)
    # Current BEA workbook layout: row 7 has 1947Q1-style period labels;
    # row 8 has the line number, GDP title and BEA series code A191RX.
    # The published values are millions, while GDPC1 is in billions.
    text=' '.join(str(v) for row in rows[:8] for v in row.values() if v)
    base=re.search(r'(millions|billions)\\s+of\\s+chained\\s*\\(?\\s*(\\d{4})\\s*\\)?\\s+dollars',text,re.I)
    if not base:raise ValueError('BEA real GDP units not explicit')
    scale=.001 if base[1].lower()=='millions' else 1.
    units=f'billions of chained {base[2]} dollars'
    headers=next((row for row in rows[:12] if sum(bool(re.fullmatch(r'(?:19|20)\\d{2}Q[1-4]',str(v or '').strip())) for v in row.values())>=4),None)
    if headers is None:raise ValueError('BEA GDP quarterly period header missing')
    values=next((row for row in rows if str(row.get(3) or '').strip()=='A191RX'
                 and 'gross domestic product' in str(row.get(2) or '').lower()),None)
    if values is None:raise ValueError('BEA real GDP A191RX row missing')
    result=[]
    for col,value in headers.items():
        m=re.fullmatch(r'((?:19|20)\\d{2})Q([1-4])',str(value or '').strip())
        if not m:continue
        day=f'{int(m[1]):04d}-{1+3*(int(m[2])-1):02d}-01'
        raw=values.get(col)
        try:
            numeric=float(str(raw).replace(',',''))*scale
        except (TypeError,ValueError):
            continue
        row=current_observation('GDPC1',day,numeric,'bea_current_workbook',URL,observed_at,units)
        if row:result.append(row)
    if not result:raise ValueError('BEA GDP table has no quarterly observations')
    return result

async def observations(client,observed_at):
    response=await client.get(URL,timeout=30,follow_redirects=True);response.raise_for_status()
    if len(response.content)>15_000_000:raise ValueError('BEA workbook transfer exceeds limit')
    return gdp_workbook(response.content,observed_at)
