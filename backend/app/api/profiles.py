
import logging
import re
from typing import Any, Awaitable, Callable
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
)
from pydantic import BaseModel, ConfigDict, Field

from app.services.profile_service import (
    ProfileService,
    ProfileServiceError,
    ProfileAccessError,
    ProfileConflictError,
)

from app.services.document_processor import (
    AuthenticationError,
    AuthorizationError,
    DocumentProcessingError,
)

from app.services.cloud_authorization import (
    CloudProcessingNotAuthorized,
)
from app.services.report_renderer import render_report_json
from app.services.gemini_client import (
    GeminiConfigurationError,
    GeminiError,
    GeminiQuotaError,
)


logger = logging.getLogger(__name__)

# Defence in depth: these error messages are already credential-free, but
# anything key- or token-shaped is redacted before logging or display.
_SECRET_LIKE = re.compile(
    r"AIza[0-9A-Za-z_\-]{10,}"
    r"|AQ\.[0-9A-Za-z_\-.]{10,}"
    r"|sb_(?:secret|publishable)_[0-9A-Za-z_\-]{6,}"
    r"|eyJ[0-9A-Za-z_\-.]{20,}"
    r"|Bearer\s+\S+",
    re.IGNORECASE,
)

_UNCHANGED = " Your saved draft has not been changed."

# Fixed pipeline messages describing a problem with the input documents.
_INPUT_PROBLEMS = (
    "No documents were confidently identified as relevant",
    "Relevant documents contain no usable text",
    "No readable documents are available for profiling",
)


def _safe_message(error: Exception, limit: int = 300) -> str:
    text = " ".join(str(error).split())
    return _SECRET_LIKE.sub("<redacted>", text)[:limit]


def report_for(draft) -> dict | None:
    """Rendered report for a draft's saved edited_data (additive field).

    Uses the same renderer as the submitted DOCX. A rendering problem never
    breaks the draft response; it is logged and the report is omitted.
    """
    if not isinstance(draft, dict) or not draft.get("edited_data"):
        return None
    try:
        return render_report_json(draft["edited_data"], {
            "generation_number": draft.get("generation_number"),
            "updated_at": draft.get("updated_at"),
        })
    except Exception as error:  # noqa: BLE001
        logger.warning("Report rendering failed: %s: %s",
                       type(error).__name__, _safe_message(error))
        return None


def _log_failure(kind: str, error: Exception) -> None:
    """One log line: failure kind, exception type and its safe message.

    No traceback, document text, tokens or credentials are logged.
    """
    logger.warning(
        "Profile generation %s: %s: %s",
        kind, type(error).__name__, _safe_message(error),
    )


router = APIRouter(
    prefix="/api/inventions",
    tags=["Invention Profiling"]
)


# --------------------------------------------------
# Request schemas
# --------------------------------------------------

class GenerateProfileRequest(BaseModel):
    """Optional body; consent defaults to False (generation is then blocked)."""

    model_config = ConfigDict(extra="forbid")

    # Innovator's explicit confirmation that the documents may be sent to
    # Google's free Gemini API. Not stored in the database.
    cloud_processing_consent: bool = False


class RegenerateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: str = Field(
        min_length=1,
        max_length=100
    )

    cloud_processing_consent: bool = False


class SaveProfileDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edited_data: dict[str, Any]

    expected_updated_at: str = Field(
        min_length=1,
        max_length=100
    )


# --------------------------------------------------
# Authentication
# --------------------------------------------------

def require_access_token(
    authorization: str | None = Header(default=None)
) -> str:
    """
    Extract the Supabase Bearer token.

    Actual token validation and ownership checks
    are performed by ProfileService.
    """

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
            headers={
                "WWW-Authenticate": "Bearer"
            }
        )

    scheme, separator, token = (
        authorization.partition(" ")
    )

    if (
        not separator
        or scheme.lower() != "bearer"
        or not token.strip()
    ):
        raise HTTPException(
            status_code=401,
            detail="A valid Bearer token is required.",
            headers={
                "WWW-Authenticate": "Bearer"
            }
        )

    return token.strip()


# --------------------------------------------------
# Centralized error handling
# --------------------------------------------------

async def execute_profile_operation(
    operation: Callable[[], Awaitable[Any]]
) -> Any:
    """
    Convert service errors into HTTP responses.

    Avoid exposing internal credentials,
    private document content, or raw AI output
    in unexpected error responses.
    """

    try:
        return await operation()

    except AuthenticationError as error:
        raise HTTPException(
            status_code=401,
            detail="Authentication required."
        ) from error

    except AuthorizationError as error:
        raise HTTPException(
            status_code=404,
            detail="Invention not found or access denied."
        ) from error

    except ProfileAccessError as error:
        message = str(error)

        if "not found or access denied" in message.lower():
            raise HTTPException(
                status_code=404,
                detail="Invention not found or access denied."
            ) from error

        raise HTTPException(
            status_code=401,
            detail="Session invalid or profile access denied."
        ) from error

    except ProfileConflictError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error)
        ) from error

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error)
        ) from error

    except DocumentProcessingError as error:
        _log_failure("failed (documents)", error)
        raise HTTPException(
            status_code=502,
            detail="Invention document processing failed."
        ) from error

    except ProfileServiceError as error:
        raise HTTPException(
            status_code=503,
            detail="Profile storage service unavailable."
        ) from error

    # AI errors are raised before any draft write, so saved data is intact.
    except CloudProcessingNotAuthorized as error:
        _log_failure("blocked", error)
        raise HTTPException(
            status_code=403,
            detail=str(error)
        ) from error

    except GeminiQuotaError as error:
        _log_failure("failed (quota)", error)
        raise HTTPException(
            status_code=429,
            detail=(
                "The Gemini free-tier quota is currently exhausted. "
                "Try again later. Your saved draft has not been changed."
            )
        ) from error

    except GeminiConfigurationError as error:
        _log_failure("failed (configuration)", error)
        raise HTTPException(
            status_code=503,
            detail=(
                "The AI service is not configured on the server. "
                "Your saved draft has not been changed."
            )
        ) from error

    except GeminiError as error:
        # Gemini messages contain only codes/statuses, never document text.
        _log_failure("failed (Gemini)", error)
        message = _safe_message(error)
        if "HTTP 503" in message:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Google Gemini is temporarily overloaded (HTTP 503 after "
                    "one retry). Try again in a few minutes." + _UNCHANGED
                )
            ) from error
        raise HTTPException(
            status_code=502,
            detail=f"AI profile generation failed: {message}" + _UNCHANGED
        ) from error

    except RuntimeError as error:
        _log_failure("failed", error)
        message = str(error)
        if message.startswith(_INPUT_PROBLEMS):
            raise HTTPException(
                status_code=422,
                detail=_safe_message(error) + _UNCHANGED
            ) from error
        # Unexpected: keep the generic message; the cause is in the log.
        raise HTTPException(
            status_code=502,
            detail=(
                "AI profile generation failed. "
                "Your saved draft has not been changed."
            )
        ) from error


# --------------------------------------------------
# GET: Retrieve saved profile draft
# --------------------------------------------------

@router.get(
    "/{invention_id}/profile/draft"
)
async def get_profile_draft(
    invention_id: UUID,
    access_token: str = Depends(
        require_access_token
    )
):
    """
    Retrieve the existing saved draft.

    Does not run the AI model.
    """

    draft = await execute_profile_operation(
        lambda: ProfileService().get_draft(
            invention_id=str(invention_id),
            access_token=access_token
        )
    )

    return {
        "status": (
            "not_generated"
            if draft is None
            else "draft_available"
        ),
        "invention_id": str(invention_id),
        "draft": draft,
        "report": report_for(draft)
    }


# --------------------------------------------------
# POST: Generate initial AI profile
# --------------------------------------------------

@router.post(
    "/{invention_id}/profile/generate"
)
async def generate_profile_draft(
    invention_id: UUID,
    body: GenerateProfileRequest | None = None,
    access_token: str = Depends(
        require_access_token
    )
):
    """
    Generate a draft using Google Gemini (authorized inventions only).

    Requires {"cloud_processing_consent": true} from the consent dialog.
    If a draft already exists, return HTTP 409.
    Do not overwrite existing drafts.
    """

    consent = bool(body and body.cloud_processing_consent)

    draft = await execute_profile_operation(
        lambda: ProfileService().generate_draft(
            invention_id=str(invention_id),
            access_token=access_token,
            regenerate=False,
            cloud_processing_consent=consent
        )
    )

    return {
        "status": "draft_generated",
        "invention_id": str(invention_id),
        "draft": draft,
        "report": report_for(draft)
    }


# --------------------------------------------------
# POST: Explicitly regenerate AI profile
# --------------------------------------------------

@router.post(
    "/{invention_id}/profile/regenerate"
)
async def regenerate_profile_draft(
    invention_id: UUID,
    body: RegenerateProfileRequest,
    access_token: str = Depends(
        require_access_token
    )
):
    """
    Generate again only on explicit request.

    expected_updated_at prevents replacing
    a draft that changed in another session.
    """

    draft = await execute_profile_operation(
        lambda: ProfileService().generate_draft(
            invention_id=str(invention_id),
            access_token=access_token,
            regenerate=True,
            expected_updated_at=(
                body.expected_updated_at
            ),
            cloud_processing_consent=body.cloud_processing_consent
        )
    )

    return {
        "status": "draft_regenerated",
        "invention_id": str(invention_id),
        "draft": draft,
        "report": report_for(draft)
    }


# --------------------------------------------------
# PUT: Autosave innovator edits
# --------------------------------------------------

@router.put(
    "/{invention_id}/profile/draft"
)
async def save_profile_draft(
    invention_id: UUID,
    body: SaveProfileDraftRequest,
    access_token: str = Depends(
        require_access_token
    )
):
    """
    Persist the innovator's edited profile.

    This does not approve or publish the draft.
    """

    draft = await execute_profile_operation(
        lambda: ProfileService().save_edits(
            invention_id=str(invention_id),
            access_token=access_token,
            edited_data=body.edited_data,
            expected_updated_at=(
                body.expected_updated_at
            )
        )
    )

    return {
        "status": "draft_saved",
        "invention_id": str(invention_id),
        "draft": draft,
        "report": report_for(draft)
    }
