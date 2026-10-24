"""Public, read-only endpoint contracts; never print credentials or response bodies."""
import asyncio
import json
import sys
from datetime import datetime,timezone
from pathlib import Path
import httpx
API_DIR=Path(__file__).resolve().parents[1];sys.path.insert(0,str(API_DIR))
from app.providers.macro import MacroProvider,SERIES
from app.providers.public_macro_pages import calendar_fallback


async def main():
    stamp=datetime.now(timezone.utc).isoformat();report={'observed_at':stamp,'series':{},'errors':[]}
    async with httpx.AsyncClient(timeout=25,headers={'User-Agent':'StocksAnalyzer public data contract check'}) as client:
        provider=MacroProvider()
        for series in SERIES:
            try:
                rows=await provider.observations(client,series,stamp)
                report['series'][series]={'rows':len(rows),'source':rows[0]['source'],'latest':max(r['observation_date'] for r in rows)}
            except Exception as exc:
                report['errors'].append({'source':series,'type':type(exc).__name__})
        try:
            events,partial=await calendar_fallback(client,stamp)
            report['bls_html_calendar']={'events':len(events),'missing_months':len(partial)}
        except Exception as exc:report['errors'].append({'source':'bls_html_calendar','type':type(exc).__name__})
    # Independent schema evidence for the binary BEA contract (no data values).
    try:
        from app.providers.bea_public import URL,gdp_workbook,cells,NS
        from zipfile import ZipFile
        from io import BytesIO
        import xml.etree.ElementTree as ET
        async with httpx.AsyncClient(timeout=30) as client:
            response=await client.get(URL,follow_redirects=True);response.raise_for_status()
        report['bea_contract']={'bytes':len(response.content)}
        with ZipFile(BytesIO(response.content)) as z:
            book=ET.fromstring(z.read('xl/workbook.xml'))
            report['bea_contract']['sheets']=[x.get('name') for x in book.findall('s:sheets/s:sheet',NS)][:15]
        report['bea_contract']['parsed_rows']=len(gdp_workbook(response.content,stamp))
    except Exception as exc:
        report.setdefault('bea_contract',{})['error']=type(exc).__name__
        if isinstance(exc,ValueError):report['bea_contract']['detail']=str(exc)[:120]
        # Public workbook layout diagnostics only: inspect header labels, never
        # infer historical observations or record unknown GDP as verified.
        try:
            from app.providers.bea_public import cells,NS
            with ZipFile(BytesIO(response.content)) as z:
                from app.providers.bea_public import gdp_workbook
                import posixpath
                book=ET.fromstring(z.read('xl/workbook.xml'))
                rels=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
                rid=next(x.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                    for x in book.findall('s:sheets/s:sheet',NS) if x.get('name')=='T10106-Q')
                target=next(x.get('Target') for x in rels if x.get('Id')==rid)
                sheetpath=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
                shared=[]
                if 'xl/sharedStrings.xml' in z.namelist():
                    shared=[''.join(x.itertext()) for x in ET.fromstring(z.read('xl/sharedStrings.xml'))]
                rows=cells(ET.fromstring(z.read(sheetpath)),shared)
                gi=next((i for i,row in enumerate(rows) if any('gross domestic product' in str(v or '').lower() for v in row.values())),None)
                report['bea_contract']['layout']={'gdp_row':gi,
                    'header':[{str(k):str(v)[:25] for k,v in sorted(row.items())[:12]} for row in rows[:8]],
                    'gdp_sample':{str(k):str(v)[:18] for k,v in sorted(rows[gi].items())[:18]} if gi is not None else {}}
        except Exception as diag:
            report.setdefault('bea_contract',{})['diagnostic_error']=type(diag).__name__
    print(json.dumps(report,indent=2),flush=True)
    # The GDP parser and the current GDP source are required contracts. A green
    # workflow must never conceal an unusable quarterly GDP feed.
    if 'GDPC1' not in report['series'] or not report.get('bea_contract',{}).get('parsed_rows'):
        raise SystemExit('Required GDP public-source contract failed; see sanitized report above')
    return report


if __name__=='__main__':asyncio.run(main())
