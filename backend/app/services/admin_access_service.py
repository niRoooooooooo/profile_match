"""Read the caller's administrative access record from Supabase.

Trust model
- The access token is verified by Supabase Auth through the existing
  document_processor.verify_user() helper; the verified user UUID is the only
  identity used.
- Roles, status and permission assignments come only from server-controlled
  database records, read through the SECURITY DEFINER function
  public.admin_get_my_access(). That function returns the caller's own record
  only (keyed on auth.uid()); the administrative tables themselves are not
  readable or writable by ordinary authenticated users.
- Roles sent by the browser, the development Role Switcher, request bodies,
  browser storage, user metadata or user_profiles.role are never consulted.
- The request runs with the publishable key and the user's own JWT. No
  service-role or secret key is used or required.

Failure handling is closed: missing configuration, an unreachable Supabase,
a missing database function or a malformed response raises
AdminAccessUnavailableError (HTTP 503). It never yields access.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urlparse
from uuid import UUID

import httpx

from app.config import SUPABASE_KEY, SUPABASE_URL
from app.core.admin_permissions import (
    AccountStatus,
    AdminRole,
    Permission,
    effective_permissions,
    parse_permission,
    parse_permissions,
    parse_role,
    parse_status,
)
from app.services.document_processor import (
    AuthenticationError,
    DocumentProcessingError,
    verify_user,
)

logger = logging.getLogger(__name__)

ACCESS_FUNCTION = "admin_get_my_access"


class AdminAccessError(Exception):
    """Base class for administrative authorization failures."""


class AdminAuthenticationError(AdminAccessError):
    """Missing, invalid or expired Supabase session (HTTP 401)."""


class AdminAccessUnavailableError(AdminAccessError):
    """Authorization infrastructure is unavailable or misconfigured (HTTP 503)."""


@dataclass(frozen=True)
class AdminAccess:
    """The verified caller's administrative access. Immutable."""

    user_id: str
    role: AdminRole | None = None
    status: AccountStatus | None = None
    assigned_permissions: frozenset[Permission] = field(default_factory=frozenset)

    @property
    def has_admin_role(self) -> bool:
        return self.role is not None

    @property
    def is_administrator(self) -> bool:
        return self.role is AdminRole.ADMINISTRATOR

    @property
    def is_admin_employee(self) -> bool:
        return self.role is AdminRole.ADMIN_EMPLOYEE

    @property
    def is_active(self) -> bool:
        return self.status is AccountStatus.ACTIVE

    @property
    def effective_permissions(self) -> frozenset[Permission]:
        return effective_permissions(self.role, self.status, self.assigned_permissions)

    def has_permission(self, permission: Permission | str) -> bool:
        parsed = parse_permission(permission)
        return parsed is not None and parsed in self.effective_permissions


class AdminAccessService:
    """Fetches and interprets the caller's administrative access record."""

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
            # A secret key would bypass Row Level Security. Refuse it.
            raise AdminAccessUnavailableError("A publishable key is required, not a secret key.")
        self._url = url
        self._key = publishable_key
        self._timeout = httpx.Timeout(timeout, connect=min(timeout, 10.0))
        self._transport = transport

    async def get_access(self, access_token: str) -> AdminAccess:
        """Verify the token and return the caller's administrative access.

        Ordinary users (no administrative record) receive an AdminAccess with
        no role and no permissions.
        """
        if not isinstance(access_token, str) or not access_token.strip():
            raise AdminAuthenticationError("Authentication required.")
        token = access_token.strip()

        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            try:
                user_id = await verify_user(client, token)
            except AuthenticationError as error:
                raise AdminAuthenticationError("Invalid or expired session.") from error
            except DocumentProcessingError as error:
                raise AdminAccessUnavailableError(
                    "Authentication service is unavailable.") from error

            record = await self._fetch_own_record(client, token)

        return self._interpret(user_id, record)

    async def _fetch_own_record(self, client: httpx.AsyncClient, token: str) -> dict | None:
        try:
            response = await client.post(
                f"{self._url}/rest/v1/rpc/{ACCESS_FUNCTION}",
                headers={
                    "apikey": self._key,
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json={},
            )
        except httpx.HTTPError as error:
            raise AdminAccessUnavailableError("Authorization database is unreachable.") from error

        if response.status_code == 401:
            raise AdminAuthenticationError("Invalid or expired session.")
        if response.status_code >= 400:
            # 404 = function not created yet (setup incomplete); 403 = grants
            # missing. Log only the status and PostgREST code, never the body.
            code = None
            try:
                body = response.json()
                code = body.get("code") if isinstance(body, dict) else None
            except ValueError:
                pass
            logger.warning("Administrative access lookup failed: HTTP %s, code %s",
                           response.status_code, code)
            raise AdminAccessUnavailableError("Administrative authorization is not available.")

        try:
            data = response.json()
        except ValueError as error:
            raise AdminAccessUnavailableError("Unexpected authorization response.") from error

        if data is None:
            return None
        if not isinstance(data, dict):
            raise AdminAccessUnavailableError("Unexpected authorization response.")
        return data

    @staticmethod
    def _interpret(user_id: str, record: dict | None) -> AdminAccess:
        if record is None:
            return AdminAccess(user_id=user_id)

        # The database function is keyed on auth.uid(); a mismatch means
        # something is wrong, so refuse rather than guess.
        try:
            record_user = str(UUID(str(record.get("user_id"))))
        except (TypeError, ValueError) as error:
            raise AdminAccessUnavailableError("Unexpected authorization response.") from error
        if record_user != user_id:
            raise AdminAccessUnavailableError("Authorization record does not match the session.")

        raw_permissions = record.get("permissions", [])
        if not isinstance(raw_permissions, list):
            raise AdminAccessUnavailableError("Unexpected authorization response.")
        assigned = parse_permissions(raw_permissions)
        if len(assigned) != len(set(map(str, raw_permissions))):
            logger.warning("Ignored %d unknown administrative permission value(s).",
                           len(set(map(str, raw_permissions))) - len(assigned))

        # Unknown role -> no administrative role. Unknown status -> None,
        # which is treated as restricted.
        return AdminAccess(
            user_id=user_id,
            role=parse_role(record.get("role")),
            status=parse_status(record.get("status")),
            assigned_permissions=assigned,
        )
