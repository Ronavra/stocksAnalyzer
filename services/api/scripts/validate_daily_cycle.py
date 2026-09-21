import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")
from app.db.client import get_supabase

def latest_expected_market_date():
    # Operational calendar: weekdays minus known full NYSE holidays.
    # The scheduled job runs after the close, so today is expected on weekdays.
    ny=datetime.now(ZoneInfo("America/New_York"))
    d=ny.date()
    # Before the post-close validation window, the previous completed session is expected.
    if ny.hour < 17:
        d-=timedelta(days=1)
    holidays={
      date(2026,1,1),date(2026,1,19),date(2026,2,16),date(2026,4,3),
      date(2026,5,25),date(2026,6,19),date(2026,7,3),date(2026,9,7),
      date(2026,11,26),date(2026,12,25)
    }
    while d.weekday()>=5 or d in holidays:
        d-=timedelta(days=1)
    return d

def validate(db):
    expected=latest_expected_market_date()
    prices=(db.table("price_history").select("price_date,company_id").eq("price_date",expected.isoformat()).execute().data or [])
    features=(db.table("price_features").select("feature_date,company_id").eq("feature_date",expected.isoformat()).execute().data or [])
    pc=len({x["company_id"] for x in prices}); fc=len({x["company_id"] for x in features})
    # Two known symbol/provider gaps are tolerated; broad-universe freshness is mandatory.
    ok=pc>=500 and fc>=500
    return {"ok":ok,"expected_market_date":expected.isoformat(),"latest_price_date":expected.isoformat() if pc else None,
            "latest_feature_date":expected.isoformat() if fc else None,"price_companies":pc,"feature_companies":fc,
            "error_message":None if ok else f"Freshness validation failed: expected {expected}; prices={pc}, features={fc}"}

if __name__=="__main__":
    result=validate(get_supabase())
    print(result)
    if not result["ok"]: raise SystemExit(1)
