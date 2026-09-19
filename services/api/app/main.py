from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import research

app = FastAPI(title="StocksAnalyzer API", version="0.2.0")
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:3000"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
app.include_router(research.router)

@app.get("/health")
def health(): return {"status":"ok","version":"0.2.0"}
