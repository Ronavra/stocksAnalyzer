from app.research.company_disclosures import current_reports

def test_official_disclosures_keep_acceptance_and_actual_observation_separate():
    company={'id':1,'ticker':'TEST','cik':'0000123456'}
    recent={'form':['8-K','10-Q','6-K','8-K'],
        'filingDate':['2026-10-02','2026-10-02','2026-01-01','2026-10-04'],
        'acceptanceDateTime':['2026-10-02T21:01:02Z','','','2026-10-04T23:00:00Z'],
        'accessionNumber':['0000123456-26-000001','quarter','old','future'],
        'primaryDocument':['report.htm','quarter.htm','old.htm','future.htm'],
        'items':['2.02, 9.01','','','5.02']}
    rows=current_reports(company,{'filings':{'recent':recent}},'2026-10-04T20:00:00+00:00')
    assert len(rows)==2
    assert rows[0]['published_at']=='2026-10-02T21:01:02+00:00'
    assert rows[0]['observed_at']=='2026-10-04T20:00:00+00:00'
    assert 'earnings results' in rows[0]['headline']
    assert rows[0]['source_url']=='https://www.sec.gov/Archives/edgar/data/123456/000012345626000001/report.htm'
    assert rows[1]['form']=='10-Q' and 'quarterly financial report' in rows[1]['headline']

def test_annual_amendments_proxy_and_ownership_filings_keep_official_links():
    forms=['10-K/A','DEF 14A','SCHEDULE 13D','4','S-8']
    recent={'form':forms,'filingDate':['2026-10-02']*5,'accessionNumber':[str(i) for i in range(5)],'primaryDocument':['a.htm']*5}
    rows=current_reports({'id':1,'ticker':'TEST','cik':'123'},{'filings':{'recent':recent}},'2026-10-04T20:00:00Z')
    assert [r['form'] for r in rows]==forms[:4]

def test_absent_acceptance_time_uses_conservative_filing_day_end():
    recent={'form':['8-K'],'filingDate':['2026-10-02'],'accessionNumber':['a'], 'primaryDocument':['a.htm']}
    company={'id':1,'ticker':'TEST','cik':'123'}
    assert current_reports(company,{'filings':{'recent':recent}},'2026-10-02T20:00:00Z')==[]
    rows=current_reports(company,{'filings':{'recent':recent}},'2026-10-04T20:00:00Z')
    assert rows[0]['published_at']=='2026-10-03T03:59:59+00:00'
