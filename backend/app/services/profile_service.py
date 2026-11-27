
"""Persist editable invention profile drafts with backend-only writes.

Original AI output and innovator edits are kept in Supabase PostgreSQL.
This service does not approve profiles or write to Supabase Storage.
"""

import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import httpx
from dotenv import load_dotenv
from pydantic import ValidationError

from app.agents.profiling_agent import generate_invention_profile
from app.core.account_status import ensure_active_account
from app.schemas.profile import InventionAIProfile


PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")


class ProfileServiceError(RuntimeError):
    pass


class ProfileAccessError(ProfileServiceError):
    pass


class ProfileConflictError(ProfileServiceError):
    pass


class ProfileService:
    """
    Read drafts using user-owned RLS permissions.
    Write drafts using protected backend credentials.
    """

    def __init__(self):
        self.supabase_url = os.getenv(
            "SUPABASE_URL", ""
        ).rstrip("/")

        self.publishable_key = (
            os.getenv("SUPABASE_PUBLISHABLE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
            or ""
        )

        self.secret_key = os.getenv(
            "SUPABASE_SECRET_KEY", ""
        )

        parsed = urlparse(self.supabase_url)

        if (
            parsed.scheme != "https"
            or not parsed.hostname
        ):
            raise ProfileServiceError(
                "SUPABASE_URL must be a valid HTTPS URL."
            )

        if not self.publishable_key:
            raise ProfileServiceError(
                "Supabase publishable key is missing."
            )

        if not self.secret_key.startswith("sb_secret_"):
            raise ProfileServiceError(
                "A backend Supabase secret key is required."
            )

    @staticmethod
    def _invention_uuid(invention_id: str) -> str:
        try:
            return str(UUID(str(invention_id)))

        except (
            TypeError,
            ValueError,
            AttributeError
        ) as error:
            raise ValueError(
                "A valid invention UUID is required."
            ) from error

    @staticmethod
    def _jwt(access_token: str) -> str:
        if (
            not isinstance(access_token, str)
            or not access_token.strip()
        ):
            raise ProfileAccessError(
                "An authenticated session is required."
            )

        return access_token.strip()

    @staticmethod
    def _timestamp(value: str) -> str:
        """
        Validate timestamps used for optimistic
        concurrency checks.
        """

        if (
            not isinstance(value, str)
            or not value.strip()
        ):
            raise ValueError(
                "A valid expected_updated_at is required."
            )

        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

            if (
                parsed.tzinfo is None
                or parsed.utcoffset() is None
            ):
                raise ValueError("Timezone missing.")

        except ValueError as error:
            raise ValueError(
                "A valid expected_updated_at is required."
            ) from error

        return value

    # ------------------------------------------
    # Separate user and backend credentials
    # ------------------------------------------

    def _headers(
        self,
        *,
        access_token: str | None = None,
        backend: bool = False,
        returning: bool = False
    ) -> dict:

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        if backend:

            if access_token is not None:
                raise ProfileServiceError(
                    "A user JWT must not be sent "
                    "with backend credentials."
                )

            # Secret API keys are not JWTs.
            # Do not use Authorization: Bearer
            # for the backend secret key.
            headers["apikey"] = self.secret_key

        else:

            if access_token is None:
                raise ProfileAccessError(
                    "An authenticated session is required."
                )

            headers["apikey"] = self.publishable_key

            headers["Authorization"] = (
                f"Bearer {self._jwt(access_token)}"
            )

        if returning:
            headers["Prefer"] = "return=representation"

        return headers

    # ------------------------------------------
    # Supabase HTTP requests
    # ------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        access_token: str | None = None,
        backend: bool = False,
        params: dict | None = None,
        json_body: dict | None = None,
        returning: bool = False
    ):

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(
                    30.0,
                    connect=10.0
                )
            ) as client:

                response = await client.request(
                    method,
                    f"{self.supabase_url}{path}",
                    headers=self._headers(
                        access_token=access_token,
                        backend=backend,
                        returning=returning
                    ),
                    params=params,
                    json=json_body
                )

        except httpx.HTTPError as error:
            raise ProfileServiceError(
                "Supabase could not be reached "
                "for the profile operation."
            ) from error

        if response.status_code in (401, 403):

            if backend:
                raise ProfileServiceError(
                    "Protected Supabase operation was denied. "
                    "Check the backend key and database grants."
                )

            raise ProfileAccessError(
                "Profile access was not authorized."
            )

        if response.status_code == 409:
            raise ProfileConflictError(
                "The profile draft changed or already exists. "
                "Reload and retry."
            )

        if response.status_code >= 400:
            raise ProfileServiceError(
                "Supabase rejected the profile operation "
                f"(HTTP {response.status_code})."
            )

        try:
            return response.json()

        except ValueError as error:
            raise ProfileServiceError(
                "Supabase returned an unexpected "
                "response format."
            ) from error

    # ------------------------------------------
    # Authenticate and verify ownership
    # ------------------------------------------

    async def _owner_id(
        self,
        invention_id: str,
        access_token: str
    ) -> str:

        user = await self._request(
            "GET",
            "/auth/v1/user",
            access_token=access_token
        )

        user_id = (
            user.get("id")
            if isinstance(user, dict)
            else None
        )

        if not user_id:
            raise ProfileAccessError(
                "The authenticated user could not "
                "be verified."
            )

        inventions = await self._request(
            "GET",
            "/rest/v1/inventions",
            access_token=access_token,
            params={
                "select": "id,owner_id",
                "id": f"eq.{invention_id}",
                "owner_id": f"eq.{user_id}",
                "limit": "1"
            }
        )

        if (
            not isinstance(inventions, list)
            or len(inventions) != 1
            or inventions[0].get("owner_id") != user_id
        ):
            raise ProfileAccessError(
                "Invention not found or access denied."
            )

        return user_id

    # ------------------------------------------
    # Read existing draft
    # ------------------------------------------

    async def _get_draft_row(
        self,
        invention_id: str,
        access_token: str
    ):

        rows = await self._request(
            "GET",
            "/rest/v1/invention_profile_drafts",
            access_token=access_token,
            params={
                "select": (
                    "id,invention_id,ai_generated_data,"
                    "edited_data,generation_number,"
                    "created_at,updated_at"
                ),
                "invention_id": f"eq.{invention_id}",
                "limit": "1"
            }
        )

        if not isinstance(rows, list):
            raise ProfileServiceError(
                "Unexpected draft retrieval result."
            )

        return rows[0] if rows else None

    async def get_draft(
        self,
        invention_id: str,
        access_token: str
    ):
        """
        Retrieve saved draft without running the AI model.
        """

        invention_id = self._invention_uuid(
            invention_id
        )

        await self._owner_id(
            invention_id,
            access_token
        )

        return await self._get_draft_row(
            invention_id,
            access_token
        )

    # ------------------------------------------
    # Backend-only draft creation
    # ------------------------------------------

    async def _insert_draft(
        self,
        invention_id: str,
        profile_data: dict
    ) -> dict:

        rows = await self._request(
            "POST",
            "/rest/v1/invention_profile_drafts",
            backend=True,
            json_body={
                "invention_id": invention_id,
                "ai_generated_data": profile_data,
                "edited_data": profile_data,
                "generation_number": 1
            },
            returning=True
        )

        if (
            not isinstance(rows, list)
            or len(rows) != 1
        ):
            raise ProfileServiceError(
                "Draft insert returned no profile row."
            )

        return rows[0]

    # ------------------------------------------
    # Backend-only draft updates
    # ------------------------------------------

    async def _update_draft(
        self,
        invention_id: str,
        expected_updated_at: str,
        changes: dict
    ) -> dict:
        """
        Update only if the draft has not changed
        since it was last retrieved.
        """

        expected_updated_at = self._timestamp(
            expected_updated_at
        )

        rows = await self._request(
            "PATCH",
            "/rest/v1/invention_profile_drafts",
            backend=True,
            params={
                "invention_id": f"eq.{invention_id}",
                "updated_at": (
                    f"eq.{expected_updated_at}"
                )
            },
            json_body=changes,
            returning=True
        )

        if not isinstance(rows, list):
            raise ProfileServiceError(
                "Unexpected draft update result."
            )

        if len(rows) != 1:
            raise ProfileConflictError(
                "This draft has changed. "
                "Reload before saving."
            )

        return rows[0]

    # ------------------------------------------
    # Generate or regenerate AI draft
    # ------------------------------------------

    async def generate_draft(
        self,
        invention_id: str,
        access_token: str,
        *,
        regenerate: bool = False,
        expected_updated_at: str | None = None,
        cloud_processing_consent: bool = False
    ) -> dict:
        """
        Generate only after an explicit API call.

        Existing drafts are not automatically replaced.
        cloud_processing_consent is the innovator's explicit confirmation
        that the documents may be sent to the free Gemini API; it is only
        passed through to the Profiling Agent's authorization checks.
        """

        invention_id = self._invention_uuid(
            invention_id
        )

        user_id = await self._owner_id(
            invention_id,
            access_token
        )

        existing = await self._get_draft_row(
            invention_id,
            access_token
        )

        if existing and not regenerate:
            raise ProfileConflictError(
                "A draft already exists. Load it "
                "or explicitly generate again."
            )

        if not existing and regenerate:
            raise ProfileConflictError(
                "No existing draft was found. "
                "Use Generate AI Profile."
            )

        if (
            existing
            and expected_updated_at
            != existing["updated_at"]
        ):
            raise ProfileConflictError(
                "The draft changed. Reload before "
                "generating again."
            )

        # Gemini Profiling Agent (raises before any write if blocked).
        result = await generate_invention_profile(
            invention_id,
            access_token,
            cloud_processing_consent=cloud_processing_consent
        )

        if (
            result.invention_id != invention_id
            or result.owner_id != user_id
        ):
            raise ProfileServiceError(
                "Generated profile ownership "
                "check failed."
            )

        profile_data = result.profile.model_dump(
            mode="json"
        )

        # AI generation may take a few minutes.
        # Confirm that the user's session and
        # invention ownership are still valid.
        await self._owner_id(
            invention_id,
            access_token
        )

        # Phase 5.4.3B.3: fresh application-wide account check
        # before the generated draft is persisted. A restricted
        # account (403), an invalid session (401) or an
        # unavailable/malformed status (503) saves nothing.
        await ensure_active_account(
            access_token,
            expected_user_id=user_id
        )

        if existing:

            return await self._update_draft(
                invention_id,
                expected_updated_at,
                {
                    "ai_generated_data": profile_data,
                    "edited_data": profile_data,
                    "generation_number": (
                        existing["generation_number"] + 1
                    )
                }
            )

        return await self._insert_draft(
            invention_id,
            profile_data
        )

    # ------------------------------------------
    # Autosave innovator edits
    # ------------------------------------------

    async def save_edits(
        self,
        invention_id: str,
        access_token: str,
        edited_data: dict,
        *,
        expected_updated_at: str
    ) -> dict:
        """
        Save edited data without approval.

        The original AI-generated output remains
        unchanged during this operation.
        """

        invention_id = self._invention_uuid(
            invention_id
        )

        await self._owner_id(
            invention_id,
            access_token
        )

        try:
            profile = InventionAIProfile.model_validate(
                edited_data
            )

        except ValidationError as error:
            raise ValueError(
                "Edited profile does not match "
                "the required profile schema."
            ) from error

        return await self._update_draft(
            invention_id,
            expected_updated_at,
            {
                "edited_data": profile.model_dump(
                    mode="json"
                )
            }
        )
