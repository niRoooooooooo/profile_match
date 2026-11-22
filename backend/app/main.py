
import logging
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import SUPABASE_URL, SUPABASE_KEY

# Phase 4: Secure invention document processing
from app.services.document_processor import (
    process_invention_documents,
    AuthenticationError,
    AuthorizationError,
    DocumentProcessingError
)

# Phase 4.5: Invention profile draft routes
from app.api.profiles import (
    router as profiles_router
)


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

# Register the new invention profiling endpoints.
app.include_router(profiles_router)


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


# --------------------------------------------------
# PHASE 4: SECURE DOCUMENT PROCESSING
# --------------------------------------------------

@app.post(
    "/api/inventions/{invention_id}/documents/parse",
    tags=["Invention Profiling"]
)
async def parse_invention_documents(
    invention_id: UUID,
    authorization: str | None = Header(default=None)
):
    """
    Parse private documents belonging to one invention.

    Security:
    - Requires Supabase Bearer token
    - Validates token through Supabase Auth
    - Confirms invention ownership
    - Uses private Supabase Storage
    - Does not use service-role credentials

    Returns extraction metadata and short text previews.
    """

    # Step 1: Read the authorization header.

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    scheme, separator, token = authorization.partition(" ")

    if (
        not separator
        or scheme.lower() != "bearer"
        or not token.strip()
    ):
        raise HTTPException(
            status_code=401,
            detail="A valid Bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    access_token = token.strip()

    try:
        # Step 2: Verify user, ownership and documents.

        result = await process_invention_documents(
            invention_id=str(invention_id),
            access_token=access_token
        )

        # Step 3: Prepare document extraction results.

        documents = []

        for item in result.documents:

            document_info = {
                "document_id": item.document_id,
                "filename": item.filename,
                "success": item.successful,
                "error": item.error
            }

            if item.parsed is not None:

                document_info.update({
                    "file_type": item.parsed.file_type,
                    "characters": item.parsed.character_count,
                    "total_pages": item.parsed.total_pages,
                    "truncated": item.parsed.truncated,
                    "warnings": item.parsed.warnings,
                    "text_preview": item.parsed.text[:300]
                })

            documents.append(document_info)

        # Step 4: Return the processing report.

        return {
            "status": "completed",
            "invention_id": result.invention_id,
            "invention_title": result.invention.get(
                "title"
            ),
            "total_documents": len(result.documents),
            "successful_documents": (
                result.successful_documents
            ),
            "failed_documents": (
                result.failed_documents
            ),
            "documents": documents,
            "warnings": result.warnings
        }

    except AuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"}
        ) from exc

    except AuthorizationError as exc:
        raise HTTPException(
            status_code=404,
            detail="Invention not found or access denied."
        ) from exc

    except DocumentProcessingError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc)
        ) from exc
