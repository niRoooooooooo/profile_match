"""Innovator report submission and private report retrieval routes.

Register this NEW router in app.main after reviewing the current main.py.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from app.services.profile_submission_service import (
    ProfileSubmissionService, JSON_MIME, DOCX_MIME,
)
from app.services.profile_service import (
    ProfileAccessError, ProfileConflictError, ProfileServiceError
)

router = APIRouter(prefix="/api/inventions", tags=["Invention Reports"])

class SubmitBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: str = Field(min_length=1, max_length=100)


def token_from_header(authorization: str | None):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required.")
    scheme, sep, token = authorization.partition(" ")
    if not sep or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="A valid Bearer token is required.")
    return token.strip()


def http_error(error: Exception):
    if isinstance(error, ProfileConflictError):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, ProfileAccessError):
        return HTTPException(status_code=404, detail="Invention not found or access denied.")
    if isinstance(error, (ValueError, TypeError)):
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, FileNotFoundError):
        return HTTPException(status_code=404, detail="Report not found.")
    return HTTPException(status_code=503, detail="Private report service unavailable.")


@router.post("/{invention_id}/profile/submit")
async def submit_profile(
    invention_id: UUID,
    body: SubmitBody,
    authorization: Annotated[str | None, Header()] = None,
):
    """Innovator submission; NOT management approval."""
    token = token_from_header(authorization)
    try:
        return await ProfileSubmissionService().submit(
            str(invention_id), token, body.expected_updated_at
        )
    except (ProfileServiceError, ValueError, TypeError) as exc:
        raise http_error(exc) from exc


@router.get("/{invention_id}/profile/submissions")
async def list_profile_submissions(
    invention_id: UUID,
    authorization: Annotated[str | None, Header()] = None,
):
    token = token_from_header(authorization)
    try:
        return await ProfileSubmissionService().list_submissions(str(invention_id), token)
    except (ProfileServiceError, ValueError, TypeError) as exc:
        raise http_error(exc) from exc


@router.get("/{invention_id}/profile/submissions/{submission_id}/{format_}")
async def download_profile_submission(
    invention_id: UUID,
    submission_id: str,
    format_: str,
    authorization: Annotated[str | None, Header()] = None,
):
    token = token_from_header(authorization)
    try:
        content = await ProfileSubmissionService().get_report(
            str(invention_id), token, submission_id, format_
        )
        mime = JSON_MIME if format_ == "json" else DOCX_MIME
        return Response(
            content=content,
            media_type=mime,
            headers={"Content-Disposition": f'attachment; filename="invention-report-{submission_id}.{format_}"',
                     "Cache-Control": "private, no-store"},
        )
    except (ProfileServiceError, ValueError, TypeError, FileNotFoundError) as exc:
        raise http_error(exc) from exc
