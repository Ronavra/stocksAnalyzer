import os
from datetime import datetime, timezone
import httpx
from .base import FundamentalsProvider, MarketDataProvider, ProviderValue, Provenance

class FMPProvider(MarketDataProvider, FundamentalsProvider):
    BASE_URL = "https://financialmodelingprep.com/stable"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("FMP_API_KEY")
        if not self.api_key:
            raise RuntimeError("FMP_API_KEY is not configured")

    async def _get(self, path: str, **params):
        params["apikey"] = self.api_key
        safe_url = f"{self.BASE_URL}/{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(safe_url, params=params)
            if response.status_code == 402:
                raise RuntimeError(f"FMP access unavailable for endpoint '{path}' on the current plan")
            if response.is_error:
                raise RuntimeError(f"FMP request failed for endpoint '{path}' with HTTP {response.status_code}")
            return response.json(), safe_url

    async def quote(self, ticker: str) -> ProviderValue:
        data, url = await self._get("quote", symbol=ticker)
        return ProviderValue(data, Provenance("fmp", url, datetime.now(timezone.utc)))

    async def profile(self, ticker: str) -> ProviderValue:
        data, url = await self._get("profile", symbol=ticker)
        return ProviderValue(data, Provenance("fmp", url, datetime.now(timezone.utc)))

    async def financials(self, ticker: str) -> ProviderValue:
        income, income_url = await self._get("income-statement", symbol=ticker)
        balance, _ = await self._get("balance-sheet-statement", symbol=ticker)
        cashflow, _ = await self._get("cash-flow-statement", symbol=ticker)
        return ProviderValue({"income": income, "balance": balance, "cashflow": cashflow},
            Provenance("fmp", income_url, datetime.now(timezone.utc)))

    async def analyst_estimates(self, ticker: str, period: str = "annual") -> ProviderValue:
        data, url = await self._get("analyst-estimates", symbol=ticker, period=period, page=0, limit=10)
        return ProviderValue(data, Provenance("fmp", url, datetime.now(timezone.utc)))
