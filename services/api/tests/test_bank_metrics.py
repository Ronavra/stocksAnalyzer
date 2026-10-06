from app.providers.sec_supplemental import attach_supplemental, supplemental_by_period
from app.research.financial_ranking import factors, finance_profile, BANK_FACTORS


def test_roe_uses_average_equity_and_bank_profile_does_not_include_industrial_fcf():
    values=factors({"latest":{"revenue":100,"net_income":20,"eps_diluted":2,"supplemental":{"equity":{"value":110},"cet1_ratio":{"value":.14}}},
                    "previous":{"revenue":90,"eps_diluted":1,"supplemental":{"equity":{"value":90}}}},10)
    assert values['return_on_equity']==.2 and values['cet1_ratio']==.14
    assert finance_profile({'industry':'Diversified Banks','scoring_profile':'general'})=='bank'
    assert finance_profile({'industry':'Asset Management & Custody Banks','sector':'Financials'})=='financial'
    assert 'fcf_yield' not in BANK_FACTORS and sum(BANK_FACTORS.values())==1


def test_full_long_term_debt_plus_short_term_never_adds_current_maturities_again():
    def fact(value):
        return {'units':{'USD':[{'end':'2026-06-30','filed':'2026-08-01','form':'10-Q','val':value}]}}
    data={'facts':{'us-gaap':{'LongTermDebtCurrentAndNoncurrent':fact(100),'ShortTermBorrowings':fact(10),'DebtCurrent':fact(25)}}}
    row=attach_supplemental([{'period_end':'2026-06-30','filed_date':'2026-08-01'}],data)[0]
    assert row['total_debt']==110
    later=attach_supplemental([{'period_end':'2026-06-30','filed_date':'2026-07-01'}],data)[0]
    assert 'total_debt' not in later


def test_proxy_debt_is_not_scored_as_a_complete_total():
    values=factors({"latest":{"revenue":100,"net_income":10,"eps_diluted":1,"free_cash_flow":20,"cash":5,"total_debt":100,
                                "supplemental":{"debt_basis":"long_term_debt_proxy"}},"previous":None},10)
    assert values['net_debt_to_fcf'] is None


def test_instance_accepts_only_explicit_standardized_capital_context():
    from app.providers.sec import instance_company_facts
    xml=b'''<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:d="http://xbrl.org/2006/xbrldi" xmlns:g="http://fasb.org/us-gaap/2026" xmlns:b="https://bank.example/2026">
      <context id="capital"><entity><identifier scheme="cik">1000</identifier><segment><d:explicitMember dimension="g:CapitalAdequacyApproachAxis">g:StandardizedApproachMember</d:explicitMember></segment></entity><period><instant>2026-06-30</instant></period></context>
      <context id="segment"><entity><identifier scheme="cik">1000</identifier><segment><d:explicitMember dimension="g:BusinessSegmentAxis">b:RetailMember</d:explicitMember></segment></entity><period><instant>2026-06-30</instant></period></context>
      <unit id="ratio"><measure>pure</measure></unit><unit id="usd"><measure>USD</measure></unit>
      <b:CommonEquityTier1CapitalRatio contextRef="capital" unitRef="ratio">0.14</b:CommonEquityTier1CapitalRatio>
      <b:CommonEquityTier1CapitalRatio contextRef="segment" unitRef="ratio">0.99</b:CommonEquityTier1CapitalRatio>
      <g:Revenues contextRef="capital" unitRef="usd">999</g:Revenues>
      <b:UnverifiedSolvencyRatio contextRef="capital" unitRef="ratio">0.98</b:UnverifiedSolvencyRatio>
    </xbrl>'''
    facts=instance_company_facts(xml,1000,{'filed_date':'2026-08-01','form':'10-Q','accession_number':'0000001000-26-000001'})
    rows=facts['facts']['bank-capital']['CommonEquityTier1CapitalRatio']['units']['pure']
    assert len(rows)==1 and rows[0]['val']==.14 and rows[0]['capital_basis']=='standardized_consolidated'
    assert 'us-gaap' not in facts['facts'] and 'UnverifiedSolvencyRatio' not in facts['facts']['bank-capital']
