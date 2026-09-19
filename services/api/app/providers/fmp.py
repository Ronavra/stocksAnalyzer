import os
from datetime import datetime, timezone
import httpx
from .base import FundamentalsProvider, MarketDataProvider, ProviderValue, Provenance

class FMPProvider(MarketDataProvider, FundamentalsProvider):
    """Financial Modeling Prep adapter. Requires FMP_API_KEY server-side."""
    BASE_URL = "https://financialmodelingprep.com/stable"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("FMP_API_KEY")
        if not self.api_key:
            raise RuntimeError("FMP_API_KEY is not configured")

    async def _get(self, path: str, **params):
        params["apikey"] = self.api_key
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.BASE_URL}/{path}", params=params)
            response.raise_for_status()
            return response.json(), str(response.url).replace(self.api_key, "***")

    async def quote(self, ticker: str) -> ProviderValue:
        data, url = await self._get("quote", symbol=ticker)
        return ProviderValue(data, Provenance("fmp", url, datetime.now(timezone.utc)))

    async def financials(self, ticker: str) -> ProviderValue:
        income, income_url = await self._get("income-statement", symbol=ticker)
        balance, _ = await self._get("balance-sheet-statement", symbol=ticker)
        cashflow, _ = await self._get("cash-flow-statement", symbol=ticker)
        return ProviderValue(
            {"income": income, "balance": balance, "cashflow": cashflow},
            Provenance("fmp", income_url, datetime.now(timezone.utc)),
        )

    async def analyst_estimates(self, ticker: str, period: str = "annual") -> ProviderValue:
        data, url = await self._get("analyst-estimates", symbol=ticker, period=period, page=0, limit=10)
        return ProviderValue(data, Provenance("fmp", url, datetime.now(timezone.utc)))
