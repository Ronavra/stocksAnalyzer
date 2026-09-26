import json
import sys
from pathlib import Path

from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")

from app.db.client import get_supabase
from app.research.calibrated_model import fit_models

if __name__=="__main__":
    models,meta=fit_models(get_supabase())
    print("Walk-forward calibrated multi-horizon model")
    print(json.dumps(meta,indent=2,default=str))
    for h in sorted(models):
        d=models[h].diagnostics
        print(
            f"{h}d rows={d['training_rows']} oof={d['oof_rows']} "
            f"up={d['oof_up_rate']:.1%} raw_brier={d['raw_brier']:.4f} "
            f"calibrated_brier={d['calibrated_brier']:.4f} "
            f"baseline_brier={d['baseline_brier']:.4f} "
            f"beats_baseline={d['calibration_beats_baseline']}"
        )
