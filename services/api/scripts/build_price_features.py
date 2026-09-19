import sys, math, statistics
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase

db=get_supabase()
companies=db.table("companies").select("id,ticker").execute().data or []

def ret(a,b):
    return (b/a)-1 if a not in (None,0) and b is not None else None

for company in companies:
    rows=(db.table("price_history").select("price_date,close,volume").eq("company_id",company["id"])
          .order("price_date").execute().data or [])
    payload=[]
    for i,r in enumerate(rows):
        close=float(r["close"]); volume=float(r["volume"]) if r.get("volume") is not None else None
        r1=ret(float(rows[i-1]["close"]),close) if i>=1 else None
        m5=ret(float(rows[i-5]["close"]),close) if i>=5 else None
        m20=ret(float(rows[i-20]["close"]),close) if i>=20 else None
        vol20=None
        if i>=20:
            daily=[ret(float(rows[j-1]["close"]),float(rows[j]["close"])) for j in range(i-19,i+1)]
            vol20=statistics.stdev(daily)*math.sqrt(252) if len(daily)>1 else None
        vchg=None
        if i>=5 and volume is not None:
            prev=[float(rows[j]["volume"]) for j in range(i-5,i) if rows[j].get("volume") is not None]
            if prev and statistics.mean(prev)!=0: vchg=volume/statistics.mean(prev)-1
        fwd=ret(close,float(rows[i+5]["close"])) if i+5<len(rows) else None
        payload.append({"company_id":company["id"],"feature_date":r["price_date"],"close":close,
          "return_1d":r1,"momentum_5d":m5,"momentum_20d":m20,"volatility_20d":vol20,
          "volume_change_5d":vchg,"forward_return_5d":fwd,"forward_up_5d":(fwd>0 if fwd is not None else None)})
    for i in range(0,len(payload),250):
        db.table("price_features").upsert(payload[i:i+250],on_conflict="company_id,feature_date").execute()
    labeled=sum(x["forward_return_5d"] is not None for x in payload)
    print(company["ticker"],"features=",len(payload),"labeled_5d=",labeled)
