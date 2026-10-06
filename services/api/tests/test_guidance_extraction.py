from app.research.guidance import extract_guidance

EVENT={"accession_number":"0000001000-26-000001","filing_date":"2026-10-05","observed_at":"2026-10-06T18:00:00Z",
       "published_at":"2026-10-05T18:00:00Z","source_url":"https://www.sec.gov/Archives/edgar/data/1000/filing.htm"}


def test_explicit_annual_eps_and_revenue_ranges_have_method_units_and_evidence():
    html='<p>For full-year 2026, the company expects adjusted diluted EPS of $6.50 to $6.75 and revenue of $14.2 billion to $14.7 billion.</p>'
    rows=extract_guidance(html,1,EVENT)
    eps=next(r for r in rows if r.get('eps_guidance_low') is not None)
    revenue=next(r for r in rows if r.get('revenue_guidance_low') is not None)
    assert eps['eps_guidance_low']==6.5 and eps['eps_method']=='adjusted'
    assert revenue['revenue_guidance_low']==14.2e9 and revenue['revenue_guidance_high']==14.7e9
    assert eps['captured_at']==EVENT['observed_at'] and eps['evidence']['parser']=='explicit_annual_range_v1'


def test_quarter_actuals_withdrawn_and_ambiguous_table_values_stay_unknown():
    for html in (
        '<p>Second-quarter 2026 guidance: EPS of $1.00 to $1.20.</p>',
        '<p>Full-year 2026 reported EPS of $1.00 to $1.20.</p>',
        '<p>No guidance for full-year 2026: EPS of $1.00 to $1.20.</p>',
        '<table><tr><td>Full-year 2026 outlook EPS</td><td>1.00</td><td>1.20</td></tr></table>',
        '<p>Full-year 2026 guidance EPS of $2.00 to $1.00.</p>',
    ):
        assert extract_guidance(html,1,EVENT)==[]


def test_explicit_fiscal_year_range_in_narrative_is_supported():
    html='<p>The company expects fiscal 2027 revenue to be in the range of $12 billion to $13 billion and adjusted diluted EPS of $5.00 to $5.50.</p>'
    rows=extract_guidance(html,1,EVENT)
    assert len(rows)==2
    assert {r['fiscal_year'] for r in rows}=={2027}
