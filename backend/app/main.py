
import logging
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import SUPABASE_URL, SUPABASE_KEY


app = FastAPI(
    title="AI Industry Partner Matching Agent",
    version="0.2.0"
)

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend"

app.mount(
    "/assets",
    StaticFiles(directory=FRONTEND_DIR),
    name="assets"
)


@app.get("/")
def home():
    return {
        "message": "Partner Matching API running",
        "phase": "Innovator Module"
    }


@app.get("/login", include_in_schema=False)
def login_page():
    return FileResponse(FRONTEND_DIR / "login.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/config/public")
def public_config():
    return {
        "url": SUPABASE_URL,
        "publishableKey": SUPABASE_KEY
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/health/database")
def database_health():
    try:
        response = httpx.get(
            f"{SUPABASE_URL.rstrip('/')}/auth/v1/health",
            headers={"apikey": SUPABASE_KEY},
            timeout=10
        )
        response.raise_for_status()

        return {
            "status": "connected",
            "service": "supabase",
            "auth_api": "healthy"
        }

    except httpx.HTTPError as exc:
        logging.exception("Supabase health check failed")
        raise HTTPException(
            status_code=503,
            detail="Supabase connection failed"
        ) from exc
