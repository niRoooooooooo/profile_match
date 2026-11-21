
import logging
import httpx

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import SUPABASE_URL, SUPABASE_KEY


# Initialize FastAPI
app = FastAPI(
    title="AI Industry Partner Matching Agent",
    description="Backend API for the Innovator Module",
    version="0.1.0"
)


# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH"],
    allow_headers=["*"]
)


# Home endpoint
@app.get("/")
def home():
    return {
        "message": "Partner Matching API running",
        "phase": "Innovator Module"
    }


# FastAPI health check
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "FastAPI"
    }


# Supabase connection health check
@app.get("/api/health/database")
def database_health():
    try:
        response = httpx.get(
            f"{SUPABASE_URL.rstrip('/')}/auth/v1/health",
            headers={
                "apikey": SUPABASE_KEY
            },
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
