import subprocess, sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
PY=sys.executable

def run(name,*args):
    print(f"\n=== {name} ===",flush=True)
    subprocess.run([PY,str(HERE/name),*args],check=True)

if __name__=="__main__":
    # End-of-day workflow. Run after US regular-session closing data is available.
    run("ingest_prices.py","--all")
    run("build_price_features.py")
    run("scan_setups.py")
    run("evaluate_signals.py")
    print("\nDaily market refresh complete. New weekly signals are intentionally created only by run_weekly_cycle.py.")
