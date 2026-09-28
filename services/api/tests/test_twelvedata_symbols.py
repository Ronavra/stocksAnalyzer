import asyncio

from app.providers.twelvedata import TwelveDataProvider


def test_class_share_prices_use_provider_dot_symbol():
    provider = TwelveDataProvider(api_key="test")
    calls = []

    async def fake_get(path, **params):
        calls.append((path, params))
        return {"values": [{"datetime": "2026-09-25", "close": "500.00"}]}, "https://api.twelvedata.com/time_series"

    provider._get = fake_get
    for ticker, symbol in (("BRK-B", "BRK.B"), ("BF-B", "BF.B"), ("AAPL", "AAPL")):
        result = asyncio.run(provider.historical_prices(ticker, "2026-09-24", "2026-09-26"))
        assert calls[-1][1]["symbol"] == symbol
        assert result.value[0]["date"] == "2026-09-25"


def test_class_share_quote_uses_same_symbol():
    provider = TwelveDataProvider(api_key="test")
    calls = []

    async def fake_get(path, **params):
        calls.append((path, params))
        return {"symbol": params["symbol"]}, "https://api.twelvedata.com/quote"

    provider._get = fake_get
    result = asyncio.run(provider.quote("BRK-B"))
    assert calls == [("quote", {"symbol": "BRK.B"})]
    assert result.value["symbol"] == "BRK.B"
