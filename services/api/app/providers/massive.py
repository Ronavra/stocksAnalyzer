import os
import httpx
from urllib.parse import urlparse, parse_qsl

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
        if r.is_error:
            # URLs may contain query credentials; never log a provider URL.
            raise RuntimeError(f"Massive request failed with HTTP {r.status_code}")
        return r.json()

    async def paginated(self,path,params,max_pages=30):
        results=[]; seen=set()
        for _ in range(max_pages):
            data=await self._get(path,params)
            results.extend(data.get("results") or [])
            next_url=data.get("next_url")
            if not next_url:
                return results
            parsed=urlparse(next_url)
            if (parsed.scheme!="https" or parsed.hostname!="api.massive.com" or parsed.port not in (None,443)
                    or parsed.username or parsed.password or parsed.path!=path or next_url in seen):
                raise RuntimeError("Invalid or repeated Massive pagination link")
            seen.add(next_url)
            params={k:v for k,v in parse_qsl(parsed.query) if k.lower() not in ("apikey","api_key")}
        raise RuntimeError("Massive pagination exceeded bounded page limit; watermark not advanced")

    async def news(self,since,until):
        return await self.paginated("/v2/reference/news",{"published_utc.gte":since,"published_utc.lte":until,
                                                         "sort":"published_utc","order":"asc","limit":1000})

    async def earnings(self,ticker:str|None=None,limit:int=50000,updated_since:str|None=None):
        params={"limit":limit,"sort":"last_updated.asc" if updated_since else "date.asc"}
        if ticker:
            params["ticker"]=ticker
        if updated_since:
            params["last_updated.gte"]=updated_since
        return await self.paginated("/benzinga/v1/earnings",params)

    async def guidance(self,ticker:str|None=None,limit:int=50000,updated_since:str|None=None):
        params={"limit":limit,"sort":"last_updated.asc" if updated_since else "date.asc"}
        if ticker:
            params["ticker"]=ticker
        if updated_since:
            params["last_updated.gte"]=updated_since
        return await self.paginated("/benzinga/v1/guidance",params)
