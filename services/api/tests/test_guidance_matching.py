from app.research.guidance_matching import match


def guide(**values):
    return dict(id=1,company_id=10,fiscal_period='FY',published_at='2026-10-20T12:00:00Z',
        eps_method='adjusted',eps_guidance_low=2,eps_guidance_high=4,evidence={'excerpt':'USD adjusted EPS guidance for fiscal year ending December 31, 2026 of 2 to 4'},**values)


def estimate(**values):
    base=dict(id=2,company_id=10,fiscal_period_end='2026-12-31',period_type='annual',captured_at='2026-10-19T12:00:00Z',
        eps_consensus=2,eps_basis='adjusted',eps_currency='USD');base.update(values);return base


def test_guidance_matches_only_prior_observed_same_target_currency_and_basis():
    rows,reason=match(guide(),[estimate()],'2026-10-22T12:00:00Z')
    assert reason=='matched' and rows[0]['consensus']==2 and rows[0]['guidance_midpoint']==3
    assert rows[0]['observed_at']=='2026-10-22T12:00:00Z'
    for values in [{'eps_basis':'unknown'},{'eps_basis':'gaap'},{'eps_currency':'EUR'},
        {'captured_at':'2026-10-21T12:00:00Z'},{'fiscal_period_end':'2027-12-31'},
        {'normalization':{'issues':['eps_consensus_outside_interval']}}]:
        assert match(guide(),[estimate(**values)],'2026-10-22T12:00:00Z')[0]==[]


def test_fiscal_year_number_or_dollar_symbol_alone_is_not_an_exact_target_match():
    g=guide();g['evidence']['excerpt']='Adjusted EPS guidance for FY2026 of $2 to $4'
    assert match(g,[estimate()],'2026-10-22T12:00:00Z')[0]==[]
