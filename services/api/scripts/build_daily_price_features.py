import sys, math, statistics
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase

db=get_supabase()
companies=db.table("companies").select("id,ticker").execute().data or []

def ret(a,b):
    return (b/a)-1 if a not in (None,0) and b is not None else None

def recent_prices(company_id, limit=100):
    rows=(db.table("price_history").select("price_date,open,high,low,close,volume")
          .eq("company_id",company_id).order("price_date",desc=True).limit(limit).execute().data or [])
    by_date={}
    for row in rows: by_date[row["price_date"]]=row
    return [by_date[d] for d in sorted(by_date)]

benchmark=next((x for x in companies if x["ticker"]=="SPY"),None)
spy_rows=recent_prices(benchmark["id"]) if benchmark else []
spy_by_date={r["price_date"]:i for i,r in enumerate(spy_rows)}

for company in companies:
    rows=recent_prices(company["id"])
    if not rows: continue
    existing=(db.table("price_features").select("feature_date").eq("company_id",company["id"])
              .order("feature_date",desc=True).limit(1).execute().data or [])
    latest_feature=existing[0]["feature_date"] if existing else None
    payload=[]
    # Recompute the newest 21 sessions so 5d/10d/20d forward labels mature incrementally.
    start_i=max(0,len(rows)-21)
    for i in range(start_i,len(rows)):
        r=rows[i]; close=float(r["close"]); volume=float(r["volume"]) if r.get("volume") is not None else None
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
        range_pct=(float(r["high"])-float(r["low"]))/close if r.get("high") is not None and r.get("low") is not None and close else None
        sma20=statistics.mean(float(rows[j]["close"]) for j in range(i-19,i+1)) if i>=19 else None
        close_vs_sma20=close/sma20-1 if sma20 else None
        volume_ratio_20d=None
        if i>=19 and volume is not None:
            vols=[float(rows[j]["volume"]) for j in range(i-19,i+1) if rows[j].get("volume") is not None]
            if vols and statistics.mean(vols)!=0: volume_ratio_20d=volume/statistics.mean(vols)
        w20=[float(rows[j]["close"]) for j in range(max(0,i-19),i+1)]
        w60=[float(rows[j]["close"]) for j in range(max(0,i-59),i+1)]
        high20=max(w20) if len(w20)>=20 else None; high60=max(w60) if len(w60)>=60 else None; support60=min(w60) if len(w60)>=60 else None
        market_m5=market_m20=market_vol20=rel_m5=rel_m20=None
        si=spy_by_date.get(r["price_date"])
        if si is not None:
            sclose=float(spy_rows[si]["close"])
            market_m5=ret(float(spy_rows[si-5]["close"]),sclose) if si>=5 else None
            market_m20=ret(float(spy_rows[si-20]["close"]),sclose) if si>=20 else None
            if si>=20:
                sd=[ret(float(spy_rows[j-1]["close"]),float(spy_rows[j]["close"])) for j in range(si-19,si+1)]
                market_vol20=statistics.stdev(sd)*math.sqrt(252) if len(sd)>1 else None
            rel_m5=m5-market_m5 if m5 is not None and market_m5 is not None else None
            rel_m20=m20-market_m20 if m20 is not None and market_m20 is not None else None
        fwd=ret(close,float(rows[i+5]["close"])) if i+5<len(rows) else None
        fwd10=ret(close,float(rows[i+10]["close"])) if i+10<len(rows) else None
        fwd20=ret(close,float(rows[i+20]["close"])) if i+20<len(rows) else None
        payload.append({"company_id":company["id"],"feature_date":r["price_date"],"close":close,"return_1d":r1,
          "momentum_5d":m5,"momentum_20d":m20,"volatility_20d":vol20,"volume_change_5d":vchg,"range_pct":range_pct,
          "close_vs_sma20":close_vs_sma20,"volume_ratio_20d":volume_ratio_20d,"market_momentum_5d":market_m5,
          "market_momentum_20d":market_m20,"market_volatility_20d":market_vol20,"relative_momentum_5d":rel_m5,
          "relative_momentum_20d":rel_m20,"drawdown_20d":close/high20-1 if high20 else None,
          "drawdown_60d":close/high60-1 if high60 else None,"distance_to_support_60d":close/support60-1 if support60 else None,
          "rebound_potential_20d":high20/close-1 if high20 else None,"rebound_potential_60d":high60/close-1 if high60 else None,
          "forward_return_5d":fwd,"forward_up_5d":(fwd>0 if fwd is not None else None),
          "forward_return_10d":fwd10,"forward_up_10d":(fwd10>0 if fwd10 is not None else None),
          "forward_return_20d":fwd20,"forward_up_20d":(fwd20>0 if fwd20 is not None else None)})
    if payload: db.table("price_features").upsert(payload,on_conflict="company_id,feature_date").execute()
    print(company["ticker"],"daily_features=",len(payload),"latest_before=",latest_feature)
