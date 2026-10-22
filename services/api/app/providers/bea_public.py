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
            if name.lower()=='t10106' or re.fullmatch(r'(?:table\s*)?1\.1\.6\.?',name,re.I):
                rid=sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                target=targets[rid]
                path=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
                if not path.startswith('xl/worksheets/'):raise ValueError('Unexpected BEA sheet target')
                selected=ET.fromstring(z.read(path));break
        if selected is None:raise ValueError('BEA real GDP table 1.1.6 missing')
        rows=cells(selected,strings)
    text=' '.join(str(v) for row in rows[:8] for v in row.values() if v)
    base=re.search(r'chained\s*\(?\s*(\d{4})\s*\)?\s+dollars',text,re.I)
    if not base:raise ValueError('BEA real GDP units not explicit')
    units=f'billions of chained {base[1]} dollars'
    data_index=next((i for i,row in enumerate(rows) if any(str(v or '').strip().lower()=='gross domestic product' for v in row.values())),None)
    if data_index is None:raise ValueError('BEA gross domestic product row missing')
    header=rows[:data_index];values=rows[data_index];years={};quarters={}
    for row in header:
        current=None
        for col in range(1,max(values)+1):
            v=str(row.get(col) or '').strip()
            if re.fullmatch(r'(?:19|20)\d{2}',v):current=int(v)
            if current:years[col]=current
    for row in header:
        for col,value in row.items():
            v=str(value or '').strip()
            if v in ('I','II','III','IV'):quarters[col]=('I','II','III','IV').index(v)+1
    result=[]
    for col,q in quarters.items():
        if col not in years:continue
        day=f'{years[col]:04d}-{1+3*(q-1):02d}-01'
        row=current_observation('GDPC1',day,values.get(col),'bea_current_workbook',URL,observed_at,units)
        if row:result.append(row)
    if not result:raise ValueError('BEA GDP table has no quarterly observations')
    return result


async def observations(client,observed_at):
    response=await client.get(URL,timeout=30,follow_redirects=True);response.raise_for_status()
    if len(response.content)>15_000_000:raise ValueError('BEA workbook transfer exceeds limit')
    return gdp_workbook(response.content,observed_at)
