"""Administrator user directory: calls public.admin_list_users() (Phase 5.5.2)
and public.admin_get_user_details() (Phase 5.5.3).

Trust model
- The request runs with the publishable key and the CALLER'S OWN Supabase
  access token. The database function derives the caller from auth.uid() and
  enforces users.view and the global account status itself (migration 006),
  in addition to the FastAPI permission dependency. The secret key is never
  used here.
- auth.users is never queried directly; only the deployed RPC is called.
- Responses are validated strictly (schemas.admin_users); anything unexpected
  fails closed with AdminAccessUnavailableError (HTTP 503).
- Nothing about the returned users or the token is logged; only HTTP status
  codes and PostgreSQL error codes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.config import SUPABASE_KEY, SUPABASE_URL
from app.schemas.admin_users import UserDetails, UserDirectoryPage
from app.services.admin_access_service import (
    AdminAccessUnavailableError,
    AdminAuthenticationError,
)

logger = logging.getLogger(__name__)

LIST_FUNCTION = "admin_list_users"
DETAILS_FUNCTION = "admin_get_user_details"


class DirectoryUserNotFoundError(Exception):
    """The target account does not exist (SQLSTATE P0002) -> HTTP 404."""


class DirectoryForbiddenError(Exception):
    """The database refused the caller (SQLSTATE 42501) -> HTTP 403."""


class DirectoryInvalidArgumentError(Exception):
    """The database rejected an argument (SQLSTATE 22023) -> HTTP 400."""


@dataclass(frozen=True)
class DirectoryQuery:
    """Exactly the argument contract of public.admin_list_users()."""

    search: str | None = None
    account_status: str | None = None
    admin_role: str | None = None
    actor: str | None = None
    position: str | None = None
    limit: int = 20
    offset: int = 0

    def rpc_arguments(self) -> dict:
        search = (self.search or "").strip() or None
        return {
            "p_search": search,
            "p_account_status": self.account_status,
            "p_admin_role": self.admin_role,
            "p_actor": self.actor,
            "p_position": self.position,
            "p_limit": self.limit,
            "p_offset": self.offset,
        }


class AdminUserService:
    def __init__(
        self,
        supabase_url: str | None = SUPABASE_URL,
        publishable_key: str | None = SUPABASE_KEY,
        *,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        url = (supabase_url or "").rstrip("/")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise AdminAccessUnavailableError("Supabase URL must be a valid HTTPS URL.")
        if not publishable_key:
            raise AdminAccessUnavailableError("Supabase publishable key is missing.")
        if publishable_key.startswith("sb_secret_"):
            raise AdminAccessUnavailableError("A publishable key is required, not a secret key.")
        self._url = url
        self._key = publishable_key
        self._timeout = httpx.Timeout(timeout, connect=min(timeout, 10.0))
        self._transport = transport

    async def _call(self, access_token: str, function: str, arguments: dict) -> object:
        """POST /rest/v1/rpc/<function> with the caller's own token.

        Returns the parsed JSON body; maps PostgREST/PostgreSQL errors.
        Logs only HTTP status and SQLSTATE (never tokens or user data).
        """
        if not isinstance(access_token, str) or not access_token.strip():
            raise AdminAuthenticationError("Authentication required.")
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(
                    f"{self._url}/rest/v1/rpc/{function}",
                    headers={
                        "apikey": self._key,
                        "Authorization": f"Bearer {access_token.strip()}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json=arguments,
                )
        except httpx.HTTPError as error:
            raise AdminAccessUnavailableError("User directory is unreachable.") from error

        if response.status_code == 401:
            raise AdminAuthenticationError("Invalid or expired session.")
        if response.status_code >= 400:
            code = None
            try:
                body = response.json()
                code = body.get("code") if isinstance(body, dict) else None
            except ValueError:
                pass
            if code == "42501":
                raise DirectoryForbiddenError("Not authorized to view registered users.")
            if code == "22023":
                raise DirectoryInvalidArgumentError("Invalid directory query.")
            if code == "P0002":
                raise DirectoryUserNotFoundError("User not found.")
            # e.g. 404 PGRST202 (function missing), 5xx: status and code only.
            logger.warning("User directory %s failed: HTTP %s, code %s",
                           function, response.status_code, code)
            raise AdminAccessUnavailableError("User directory is not available.")

        try:
            return response.json()
        except ValueError as error:
            raise AdminAccessUnavailableError("Unexpected user directory response.") from error

    async def list_users(self, access_token: str, query: DirectoryQuery) -> UserDirectoryPage:
        payload = await self._call(access_token, LIST_FUNCTION, query.rpc_arguments())
        try:
            page = UserDirectoryPage.model_validate(payload)
        except ValidationError as error:
            logger.warning("User directory response failed validation (%d error(s)).",
                           error.error_count())
            raise AdminAccessUnavailableError("Unexpected user directory response.") from error
        # The function echoes the requested window; anything else is unexpected.
        if page.limit != query.limit or page.offset != query.offset:
            raise AdminAccessUnavailableError("Unexpected user directory response.")
        return page

    async def get_user_details(self, access_token: str, user_id: UUID, *,
                               caller_is_administrator: bool) -> UserDetails:
        """Details of ONE target account (user_id is the target, never the caller).

        Fails closed (503) when the record is malformed, belongs to another
        user, or contains restriction reasons although the caller is not a
        full active Administrator.
        """
        payload = await self._call(access_token, DETAILS_FUNCTION, {"p_user_id": str(user_id)})
        try:
            details = UserDetails.model_validate(payload)
        except ValidationError as error:
            logger.warning("User details response failed validation (%d error(s)).",
                           error.error_count())
            raise AdminAccessUnavailableError("Unexpected user details response.") from error
        if details.user_id != user_id:
            raise AdminAccessUnavailableError("User details do not match the requested account.")
        if not caller_is_administrator and details.contains_restriction_reasons():
            logger.warning("User details contained restriction reasons for a non-Administrator caller.")
            raise AdminAccessUnavailableError("Unexpected user details response.")
        return details
