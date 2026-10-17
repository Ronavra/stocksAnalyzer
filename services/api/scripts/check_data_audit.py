"""Verify the complete audit route against the hosted database, within UI deadline."""
import json
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))
load_dotenv(API_DIR / ".env")
from fastapi.testclient import TestClient
from app.main import app


def main():
    started = time.monotonic()
    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/research/data-audit")
    elapsed = time.monotonic() - started
    if response.status_code != 200:
        raise RuntimeError(f"Data audit returned HTTP {response.status_code}")
    data = response.json()
    total = data.get("universe", 0)
    if total <= 0 or len(data.get("source_families", [])) != 15:
        raise RuntimeError("Data audit omitted the company universe or source families")
    if any(f["total"] != total or sum(f["status_counts"].values()) != total
           for f in data["source_families"]):
        raise RuntimeError("Data audit source-family counts do not reconcile")
    if len(data.get("company_gaps", [])) != total:
        raise RuntimeError("Data audit omitted per-company evidence gaps")
    if elapsed >= 25:
        raise RuntimeError("Data audit approaches the client 30-second timeout")
    report = {"universe": total, "source_families": len(data["source_families"]),
              "company_gaps": len(data["company_gaps"]), "elapsed_seconds": round(elapsed, 3),
              "response_bytes": len(response.content), "all_major_data_complete": data["all_major_data_complete"]}
    (API_DIR / "data_audit_check.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
