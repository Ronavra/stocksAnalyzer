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
    print(json.dumps(report,indent=2),flush=True)
    # Public availability is observed, not an excuse to mask an outage as complete.
    return report


if __name__=='__main__':asyncio.run(main())
