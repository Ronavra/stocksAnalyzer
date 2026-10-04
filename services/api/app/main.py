from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import logging
from .db.client import get_supabase
from fastapi.middleware.cors import CORSMiddleware
from .routers import research

app = FastAPI(title="StocksAnalyzer API", version="0.2.0")
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:3000"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
app.include_router(research.router)

@app.get("/health")
def health(): return {"status":"ok","version":"0.2.0"}

@app.get("/ready")
def ready():
    try:
        get_supabase().table("companies").select("id").limit(1).execute()
    except Exception as exc:
        logging.getLogger(__name__).error("Readiness failed: %s", type(exc).__name__)
        return JSONResponse(status_code=503,content={"status":"unavailable","database":"unavailable"})
    return {"status":"ready","database":"connected"}

@app.exception_handler(Exception)
async def data_error(request, exc):
    logging.getLogger(__name__).error("Request %s failed: %s", request.url.path, type(exc).__name__)
    return JSONResponse(status_code=503,content={"detail":"Research data temporarily unavailable. Retry shortly.","code":"DATA_UNAVAILABLE"})
