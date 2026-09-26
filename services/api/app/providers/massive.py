import os
import httpx

BASE_URL="https://api.massive.com"

class MassiveProvider:
    def __init__(self, api_key: str|None=None):
        self.api_key=api_key or os.getenv("MASSIVE_API_KEY")
        if not self.api_key:
            raise RuntimeError("MASSIVE_API_KEY is not configured")

    async def _get(self,path:str,params:dict|None=None):
        headers={"Authorization":f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=45) as client:
            r=await client.get(f"{BASE_URL}{path}",params=params or {},headers=headers)
        if r.status_code in (401,403):
            raise RuntimeError("Massive access denied; check API key and dataset subscription")
        if r.status_code==429:
            raise RuntimeError("Massive rate limit reached")
        r.raise_for_status()
        return r.json()

    async def earnings(self,ticker:str|None=None,limit:int=50000,updated_since:str|None=None):
        params={"limit":limit,"sort":"last_updated.asc" if updated_since else "date.asc"}
        if ticker:
            params["ticker"]=ticker
        if updated_since:
            params["last_updated.gte"]=updated_since
        return (await self._get("/benzinga/v1/earnings",params)).get("results",[])

    async def guidance(self,ticker:str|None=None,limit:int=50000,updated_since:str|None=None):
        params={"limit":limit,"sort":"last_updated.asc" if updated_since else "date.asc"}
        if ticker:
            params["ticker"]=ticker
        if updated_since:
            params["last_updated.gte"]=updated_since
        return (await self._get("/benzinga/v1/guidance",params)).get("results",[])
