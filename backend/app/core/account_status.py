"""Application-wide account status for Innovator business APIs (Phase 5.4.3B).

Every Innovator business route depends on ``require_active_user``, which runs
BEFORE the route body and therefore before any ownership check, AI call or
server-side (secret-key) Supabase operation:

    1. Bearer token extracted (existing app.core.admin_access.bearer_token).
    2. Token verified by Supabase Auth through the existing
       document_processor.verify_user() helper (publishable key + the user's
       own token; the secret key is never used to establish identity).
    3. The caller's own record is read with the SAME token from the existing
       SECURITY DEFINER function public.institutional_get_my_access()
       (keyed on auth.uid()). Its user_id must equal the verified user, and
       its account_status field must be present:
         null                    -> no restriction record -> active
         "active"                -> active
         "suspended" / "banned"  -> 403
         any other value         -> 403 (unknown never grants access)
    4. Only then does the route run; its existing ownership checks and
       processing are unchanged.

HTTP errors: 401 missing/invalid/expired authentication; 403 restricted
account; 503 malformed or mismatched record, missing field, or unavailable
authorization infrastructure. Nothing is cached between requests.

The Supabase URL and publishable key are read from document_processor at
call time, i.e. exactly the project verify_user() uses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache

import httpx
from fastapi import Depends, HTTPException, status

from app.core.admin_access import bearer_token
from app.core.admin_permissions import AccountStatus
from app.services import document_processor as dp
from app.services.admin_access_service import AdminAccessUnavailableError, parse_account_record

logger = logging.getLogger(__name__)

ACCOUNT_FUNCTION = "institutional_get_my_access"

RESTRICTED = "This account is restricted."
UNAVAILABLE = "Account status is temporarily unavailable."


class AccountStatusError(Exception):
    """Base class for account-status authorization failures."""


class AccountAuthenticationError(AccountStatusError):
    """Missing, invalid or expired Supabase session (HTTP 401)."""


class AccountRestrictedError(AccountStatusError):
    """Suspended, banned or unknown application-wide status (HTTP 403)."""


class AccountStatusUnavailableError(AccountStatusError):
    """Malformed record or unavailable infrastructure (HTTP 503)."""


@dataclass(frozen=True)
class ActiveAccount:
    """A verified caller whose application-wide account is active."""

    user_id: str
    access_token: str = field(repr=False)


def interpret_account_status(user_id: str, record: object) -> AccountStatus | None:
    """Status from the caller's own record. None = unknown (restricted).

    Delegates to the one shared parser (admin_access_service.
    parse_account_record) used by every authorization path. Raises
    AccountStatusUnavailableError for anything malformed.
    """
    try:
        return parse_account_record(user_id, record)
    except AdminAccessUnavailableError as error:
        raise AccountStatusUnavailableError(str(error)) from error


class AccountStatusService:
    def __init__(self, *, timeout: float = 15.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._timeout = httpx.Timeout(timeout, connect=min(timeout, 10.0))
        self._transport = transport

    async def verify_active(self, access_token: str) -> ActiveAccount:
        if not isinstance(access_token, str) or not access_token.strip():
            raise AccountAuthenticationError("Authentication required.")
        token = access_token.strip()
        url, key = (dp.SUPABASE_URL or "").rstrip("/"), dp.SUPABASE_KEY or ""
        if not url.startswith("https://") or not key or key.startswith("sb_secret_"):
            raise AccountStatusUnavailableError("Supabase configuration is invalid.")

        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            try:
                user_id = await dp.verify_user(client, token)
            except dp.AuthenticationError as error:
                raise AccountAuthenticationError("Invalid or expired session.") from error
            except dp.DocumentProcessingError as error:
                raise AccountStatusUnavailableError("Authentication service is unavailable.") from error
            record = await self._fetch_record(client, url, key, token)

        account_status = interpret_account_status(user_id, record)
        if account_status is not AccountStatus.ACTIVE:
            raise AccountRestrictedError(RESTRICTED)
        return ActiveAccount(user_id=user_id, access_token=token)

    @staticmethod
    async def _fetch_record(client: httpx.AsyncClient, url: str, key: str, token: str) -> object:
        try:
            response = await client.post(
                f"{url}/rest/v1/rpc/{ACCOUNT_FUNCTION}",
                headers={"apikey": key, "Authorization": f"Bearer {token}",
                         "Accept": "application/json", "Content-Type": "application/json"},
                json={},
            )
        except httpx.HTTPError as error:
            raise AccountStatusUnavailableError("Account status lookup is unreachable.") from error
        if response.status_code == 401:
            raise AccountAuthenticationError("Invalid or expired session.")
        if response.status_code >= 400:
            code = None
            try:
                body = response.json()
                code = body.get("code") if isinstance(body, dict) else None
            except ValueError:
                pass
            # Status and PostgREST code only; never tokens or response bodies.
            logger.warning("Account status lookup failed: HTTP %s, code %s",
                           response.status_code, code)
            raise AccountStatusUnavailableError("Account status lookup failed.")
        try:
            return response.json()
        except ValueError as error:
            raise AccountStatusUnavailableError("Unexpected account record.") from error


@lru_cache(maxsize=1)
def _default_service() -> AccountStatusService:
    return AccountStatusService()


def get_account_status_service() -> AccountStatusService:
    """Overridable dependency (stateless; nothing is cached between requests)."""
    return _default_service()


def http_error(error: AccountStatusError) -> HTTPException:
    """The one HTTP mapping: 401 / 403 / 503."""
    if isinstance(error, AccountAuthenticationError):
        return HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session.",
                             headers={"WWW-Authenticate": "Bearer"})
    if isinstance(error, AccountRestrictedError):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail=RESTRICTED)
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=UNAVAILABLE)


async def require_active_user(
    token: str = Depends(bearer_token),
    service: AccountStatusService = Depends(get_account_status_service),
) -> ActiveAccount:
    """Authenticated caller with an active application-wide account."""
    try:
        return await service.verify_active(token)
    except AccountStatusError as error:
        raise http_error(error) from error


async def ensure_active_account(access_token: str, *, expected_user_id: str | None = None
                                ) -> ActiveAccount:
    """Fresh re-check at a persistence/publication boundary inside a service.

    Raises the same HTTP 401/403/503 as the route dependency, so the existing
    route error handling passes it through unchanged. With expected_user_id,
    the token must still belong to that user (otherwise 401).
    """
    try:
        account = await get_account_status_service().verify_active(access_token)
    except AccountStatusError as error:
        raise http_error(error) from error
    if expected_user_id is not None and account.user_id != expected_user_id:
        raise http_error(AccountAuthenticationError("Session user changed."))
    return account
