
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


router = APIRouter(
    prefix="/api/inventions",
    tags=["Invention Profiling"]
)


# --------------------------------------------------
# Request schemas
# --------------------------------------------------

class RegenerateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: str = Field(
        min_length=1,
        max_length=100
    )


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
        raise HTTPException(
            status_code=502,
            detail="Invention document processing failed."
        ) from error

    except ProfileServiceError as error:
        raise HTTPException(
            status_code=503,
            detail="Profile storage service unavailable."
        ) from error

    except RuntimeError as error:
        raise HTTPException(
            status_code=502,
            detail=(
                "AI profile generation failed. "
                "Check the local Ollama service."
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

    Does not run Qwen.
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
        "draft": draft
    }


# --------------------------------------------------
# POST: Generate initial AI profile
# --------------------------------------------------

@router.post(
    "/{invention_id}/profile/generate"
)
async def generate_profile_draft(
    invention_id: UUID,
    access_token: str = Depends(
        require_access_token
    )
):
    """
    Generate a draft using local Qwen.

    If a draft already exists, return HTTP 409.
    Do not overwrite existing drafts.
    """

    draft = await execute_profile_operation(
        lambda: ProfileService().generate_draft(
            invention_id=str(invention_id),
            access_token=access_token,
            regenerate=False
        )
    )

    return {
        "status": "draft_generated",
        "invention_id": str(invention_id),
        "draft": draft
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
            )
        )
    )

    return {
        "status": "draft_regenerated",
        "invention_id": str(invention_id),
        "draft": draft
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
        "draft": draft
    }
