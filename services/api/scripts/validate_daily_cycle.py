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

from app.research.market_freshness import market_freshness

def validate(db):
    return market_freshness(db, latest_expected_market_date())

if __name__=="__main__":
    result=validate(get_supabase())
    print(result)
    if not result["ok"]:
        raise SystemExit(1)
