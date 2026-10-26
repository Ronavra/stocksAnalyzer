"""Fail closed on absent opens, and protect the frozen USD allocation."""
from scripts.track_real_money_pilot import positive,EXPECTED,USD_EACH,PILOT_ID,TRADE_DATE

def test_pilot_is_five_unique_names_and_5000_usd():
    assert EXPECTED==('COF','UBER','NVDA','SYF','DECK')
    assert len(set(EXPECTED))==5
    assert len(EXPECTED)*USD_EACH==5000
    assert TRADE_DATE=='2026-10-27'
    assert PILOT_ID.startswith('weekly-')

def test_missing_open_cannot_become_a_fake_fill():
    assert positive(None) is None
    assert positive('') is None
    assert positive(0) is None
    assert positive('-10') is None
    assert positive('NaN') is None
    assert positive('inf') is None
    assert positive('250.5')==250.5
