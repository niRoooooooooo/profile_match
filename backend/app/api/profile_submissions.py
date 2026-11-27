"""Innovator report submission and private report retrieval routes.

Register this NEW router in app.main after reviewing the current main.py.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.account_status import ActiveAccount, require_active_user
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


async def active_token(account: ActiveAccount = Depends(require_active_user)) -> str:
    """Phase 5.4.3B: authenticated caller with an ACTIVE application-wide
    account (401 / 403 / 503 otherwise). Runs before the route body, so no
    secret-key storage operation happens first. Ownership is still checked
    by ProfileSubmissionService."""
    return account.access_token


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
    token: Annotated[str, Depends(active_token)],
):
    """Innovator submission; NOT management approval."""
    try:
        return await ProfileSubmissionService().submit(
            str(invention_id), token, body.expected_updated_at
        )
    except (ProfileServiceError, ValueError, TypeError) as exc:
        raise http_error(exc) from exc


@router.get("/{invention_id}/profile/submissions")
async def list_profile_submissions(
    invention_id: UUID,
    token: Annotated[str, Depends(active_token)],
):
    try:
        return await ProfileSubmissionService().list_submissions(str(invention_id), token)
    except (ProfileServiceError, ValueError, TypeError) as exc:
        raise http_error(exc) from exc


@router.get("/{invention_id}/profile/submissions/{submission_id}/{format_}")
async def download_profile_submission(
    invention_id: UUID,
    submission_id: str,
    format_: str,
    token: Annotated[str, Depends(active_token)],
):
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
