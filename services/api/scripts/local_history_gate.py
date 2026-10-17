"""Hosted long-history jobs defer to the archive computer after retention activates."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase


def main():
    db=get_supabase()
    from app.research.model_readiness import record_history_gate
    import json
    report=record_history_gate(db)
    run=report["full_history_available"]
    (API_DIR/"model_history_gate.json").write_text(json.dumps(report,indent=2)+"\n")
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"],"a") as out: out.write(f"run={str(run).lower()}\n")
    if not run:
        note="Long-history research is assigned to the local archive computer. This hosted job cannot read the full archive; validation and promotion are skipped."
        print(note)
        if os.getenv("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"],"a") as out: out.write(note+"\n")


if __name__=="__main__": main()
