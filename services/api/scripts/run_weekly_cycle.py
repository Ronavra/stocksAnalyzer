import subprocess, sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
PY=sys.executable

def run(name,*args):
    print(f"\n=== {name} ===")
    subprocess.run([PY,str(HERE/name),*args],check=True)

if __name__=="__main__":
    # Run after the normal price/features refresh. Mature old forecasts first, then freeze today's new list.
    run("evaluate_signals.py")
    run("generate_weekly_signals.py","--top","5","--horizon","5")
    print("\nWeekly prediction cycle complete.")
