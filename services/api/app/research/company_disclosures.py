"""Official SEC reports and material filings, with actual observation times."""
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

ITEM_LABELS={'1.01':'material agreement','1.03':'bankruptcy','2.01':'acquisition/disposal',
             '2.02':'earnings results','2.03':'debt obligation','2.04':'default/acceleration',
             '2.05':'restructuring','2.06':'asset impairment','3.01':'listing notice',
             '4.02':'financial statement non-reliance','5.02':'management change',
             '7.01':'Regulation FD disclosure','8.01':'other material event'}

REPORT_LABELS={"10-K":"annual financial report", "10-Q":"quarterly financial report",
               "20-F":"annual foreign-issuer report", "40-F":"annual foreign-issuer report",
               "DEF 14A":"proxy statement", "DEFA14A":"proxy materials",
               "SC 13D":"beneficial ownership disclosure", "SC 13G":"beneficial ownership disclosure",
               "SCHEDULE 13D":"beneficial ownership disclosure", "SCHEDULE 13G":"beneficial ownership disclosure",
               "4":"insider transaction disclosure",'10-KT':'fiscal transition financial report','10-QT':'quarter transition financial report'}

def current_reports(company, submissions, observed_at, lookback_days=90):
    asof=datetime.fromisoformat(observed_at.replace('Z','+00:00')).date()
    recent=(submissions.get('filings') or {}).get('recent') or {}
    def cell(key,index,default=''):
        values=recent.get(key) or []
        return values[index] if index<len(values) else default
    rows=[]
    for index,form in enumerate(recent.get('form') or []):
        base_form=form.removesuffix('/A')
        if base_form not in ('8-K','6-K') and base_form not in REPORT_LABELS: continue
        filed=cell('filingDate',index)
        if not filed or not 0 <= (asof-date.fromisoformat(filed)).days<=lookback_days: continue
        accession=cell('accessionNumber',index); document=cell('primaryDocument',index)
        if not accession or not document: continue
        stamp=cell('acceptanceDateTime',index)
        if stamp:
            accepted=datetime.fromisoformat(stamp.replace('Z','+00:00'))
            if accepted.tzinfo is None: accepted=accepted.replace(tzinfo=ZoneInfo('America/New_York'))
        else:
            # End of filing day is conservative when no acceptance time exists.
            accepted=datetime.fromisoformat(filed+'T23:59:59').replace(tzinfo=ZoneInfo('America/New_York'))
        if accepted>datetime.fromisoformat(observed_at.replace('Z','+00:00')): continue
        items=[x.strip() for x in cell('items',index).split(',') if x.strip()]
        labels=[ITEM_LABELS[x] for x in items if x in ITEM_LABELS]
        if base_form in REPORT_LABELS:
            labels.insert(0,REPORT_LABELS[base_form])
        rows.append({'company_id':company['id'],'accession_number':accession,'form':form,
            'filing_date':filed,'published_at':accepted.astimezone(timezone.utc).isoformat(),
            'observed_at':observed_at,'items':items,
            'headline':f"{company['ticker']} · {form}"+(' · '+', '.join(labels) if labels else ' · company disclosure'),
            'source_url':f"https://www.sec.gov/Archives/edgar/data/{int(company['cik'])}/{accession.replace('-','')}/{quote(document,safe='/')}"})
    return rows
