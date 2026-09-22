import os
import asyncio
from datetime import datetime, timezone
import httpx
from .base import MarketDataProvider, ProviderValue, Provenance

class TwelveDataProvider(MarketDataProvider):
    BASE_URL="https://api.twelvedata.com"

    def __init__(self,api_key=None):
        self.api_key=api_key or os.getenv("TWELVE_DATA_API_KEY")
        if not self.api_key:
            raise RuntimeError("TWELVE_DATA_API_KEY is not configured")

    async def _get(self,path,**params):
        params["apikey"]=self.api_key
        safe_url=f"{self.BASE_URL}/{path}"
        async with httpx.AsyncClient(timeout=45) as client:
            r=None
            for attempt in range(3):
                r=await client.get(safe_url,params=params)
                if r.status_code not in (429,500,502,503,504):
                    break
                if attempt < 2:
                    await asyncio.sleep(10*(attempt+1))
            if r.is_error:
                try:
                    detail=r.json().get("message")
                except Exception:
                    detail=r.text[:300]
                raise RuntimeError(f"Twelve Data request failed for endpoint '{path}' with HTTP {r.status_code}: {detail}")
            data=r.json()
            if isinstance(data,dict) and data.get("status")=="error":
                raise RuntimeError(f"Twelve Data error for endpoint '{path}': {data.get('message','unknown provider error')}")
            return data,safe_url

    async def quote(self,ticker):
        data,url=await self._get("quote",symbol=ticker)
        return ProviderValue(data,Provenance("twelvedata",url,datetime.now(timezone.utc)))

    async def historical_prices(self,ticker,from_date,to_date):
        data,url=await self._get("time_series",symbol=ticker,interval="1day",start_date=from_date,end_date=to_date,outputsize=5000,order="asc",timezone="Exchange")
        values=data.get("values",[]) if isinstance(data,dict) else []
        rows=[{"date":v.get("datetime"),"open":v.get("open"),"high":v.get("high"),"low":v.get("low"),"close":v.get("close"),"volume":v.get("volume")} for v in values]
        return ProviderValue(rows,Provenance("twelvedata",url,datetime.now(timezone.utc)))
