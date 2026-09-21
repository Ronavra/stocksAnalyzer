import sys
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")

from app.db.client import get_supabase
from app.market_calendar import latest_completed_session

def latest_expected_market_date():
    return latest_completed_session()

def validate(db):
    expected=latest_expected_market_date()
    ds=expected.isoformat()
    prices=(db.table("price_history").select("company_id").eq("price_date",ds).execute().data or [])
    features=(db.table("price_features").select("company_id").eq("feature_date",ds).execute().data or [])
    price_ids={x["company_id"] for x in prices}
    feature_ids={x["company_id"] for x in features}
    universe=(db.table("companies").select("id,ticker").or_("is_sp500.eq.true,scoring_profile.eq.benchmark").execute().data or [])
    missing_prices=[x["ticker"] for x in universe if x["id"] not in price_ids]
    missing_features=[x["ticker"] for x in universe if x["id"] not in feature_ids]
    pc=len(price_ids); fc=len(feature_ids)
    ok=pc>=500 and fc>=500
    error=None if ok else (
        f"Freshness validation failed: expected {expected}; prices={pc}, features={fc}; "
        f"missing_prices={missing_prices[:20]}; missing_features={missing_features[:20]}"
    )
    return {"ok":ok,"expected_market_date":ds,
            "latest_price_date":ds if pc else None,"latest_feature_date":ds if fc else None,
            "price_companies":pc,"feature_companies":fc,
            "missing_prices":missing_prices,"missing_features":missing_features,
            "error_message":error}

if __name__=="__main__":
    result=validate(get_supabase())
    print(result)
    if not result["ok"]:
        raise SystemExit(1)
