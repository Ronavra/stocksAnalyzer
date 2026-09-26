import json
import sys
from pathlib import Path

from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")

from app.db.client import get_supabase
from app.research.calibrated_model import fit_models

STAGES=[
    ("price",("price",)),
    ("price_context",("price","context")),
    ("price_context_earnings",("price","context","earnings")),
    ("price_context_earnings_fundamentals",("price","context","earnings","fundamentals")),
    ("full",("price","context","earnings","fundamentals","guidance")),
]

def main():
    db=get_supabase()
    results={}
    for name,groups in STAGES:
        models,meta=fit_models(db,groups=groups)
        results[name]={"groups":groups,"meta":meta,"horizons":{}}
        for h,m in sorted(models.items()):
            d=m.diagnostics
            results[name]["horizons"][str(h)]={
                "calibrated_brier":d.get("calibrated_brier"),
                "baseline_brier":d.get("baseline_brier"),
                "brier_skill":d.get("brier_skill"),
                "beats_baseline":d.get("calibration_beats_baseline"),
                "oof_rows":d.get("oof_rows"),
            }
            print(
                f"{name:38} {h:2d}d "
                f"brier={d['calibrated_brier']:.5f} baseline={d['baseline_brier']:.5f} "
                f"skill={d.get('brier_skill'):+.2%} oof={d['oof_rows']}"
            )

    print("\nIncremental feature value (negative delta is better):")
    prior=None
    for name,_ in STAGES:
        cur=results[name]["horizons"]
        if prior:
            for h in ("5","10","20"):
                if h in cur and h in prior:
                    delta=cur[h]["calibrated_brier"]-prior[h]["calibrated_brier"]
                    print(f"{name:38} {h}d delta_brier={delta:+.6f}")
        prior=cur

    out=API_DIR/"ablation_results.json"
    out.write_text(json.dumps(results,indent=2,default=str),encoding="utf-8")
    print(f"\nSaved {out}")

if __name__=="__main__":
    main()
