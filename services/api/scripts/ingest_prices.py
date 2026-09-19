import sys
import asyncio
from datetime import date, timedelta
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.providers.fmp import FMPProvider

db=get_supabase(); provider=FMPProvider()
end=date.today(); start=end-timedelta(days=365*6)
companies=db.table("companies").select("id,ticker").execute().data or []
for c in companies:
    try:
        result=asyncio.run(provider.historical_prices(c["ticker"],str(start),str(end)))
        rows=result.value
        payload=[]
        for r in rows:
            d=r.get("date"); close=r.get("close")
            if not d or close is None: continue
            payload.append({"company_id":c["id"],"price_date":d,"open":r.get("open"),"high":r.get("high"),
              "low":r.get("low"),"close":close,"volume":r.get("volume"),"source":"fmp"})
        for i in range(0,len(payload),250):
            db.table("price_history").upsert(payload[i:i+250],on_conflict="company_id,price_date,source").execute()
        print(c["ticker"],"price rows saved=",len(payload))
    except Exception as e:
        print(c["ticker"],"price history unavailable:",e)
