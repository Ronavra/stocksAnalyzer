import os
from datetime import datetime, timezone
import httpx
from .base import ProviderValue, Provenance

class AlphaVantageProvider:
    BASE_URL="https://www.alphavantage.co/query"
    def __init__(self,api_key=None):
        self.api_key=api_key or os.getenv("ALPHA_VANTAGE_API_KEY")
        if not self.api_key: raise RuntimeError("ALPHA_VANTAGE_API_KEY is not configured")
    async def earnings(self,ticker):
        async with httpx.AsyncClient(timeout=45) as client:
            r=await client.get(self.BASE_URL,params={"function":"EARNINGS","symbol":ticker,"apikey":self.api_key})
            if r.is_error: raise RuntimeError(f"Alpha Vantage EARNINGS failed with HTTP {r.status_code}")
            data=r.json()
            if "Note" in data or "Information" in data or "Error Message" in data:
                raise RuntimeError("Alpha Vantage EARNINGS unavailable: "+str(data.get("Note") or data.get("Information") or data.get("Error Message")))
            return ProviderValue(data,Provenance("alphavantage",self.BASE_URL,datetime.now(timezone.utc)))
