"""Friday model research on the computer holding the verified archive."""
import os
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.db.market_history import require_full_history


def main():
    if not os.getenv("LOCAL_MARKET_ARCHIVE"):
        raise RuntimeError("Configure LOCAL_MARKET_ARCHIVE before scheduling local model validation")
    require_full_history(get_supabase())
    for name in ("ablation_predictive_model.py","validate_weekly_ranker.py"):
        subprocess.run([sys.executable,str(API_DIR/"scripts"/name)],cwd=API_DIR,check=True)


if __name__=="__main__": main()
