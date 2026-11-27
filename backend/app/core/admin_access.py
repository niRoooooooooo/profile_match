"""FastAPI dependencies that enforce administrative authorization.

Every protected administrative route must depend on one of:

    require_admin_account        any active Administrator or Admin Employee
    require_administrator        active Administrator only
    require_permissions(...)     active account holding every listed permission

The caller's access is re-read from Supabase on every request; nothing is
cached between requests, so a suspension or permission removal takes effect on
the next call. Since Phase 5.4.3A "active" also requires an unrestricted
application-wide account status (user_account_status): a suspended or banned
account is refused with 403 even if its administrative record is active.

HTTP errors
    401  missing, malformed, invalid or expired Bearer token
    403  no administrative role, restricted account, or missing permission
    503  authorization infrastructure unavailable (never grants access)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import lru_cache

from fastapi import Depends, Header, HTTPException, status

from app.core.admin_permissions import Permission, parse_permission
from app.services.admin_access_service import (
    AdminAccess,
    AdminAccessService,
    AdminAccessUnavailableError,
    AdminAuthenticationError,
)

_BEARER = {"WWW-Authenticate": "Bearer"}

NO_ADMIN_ACCESS = "Administrative access is not available for this account."
RESTRICTED_ACCOUNT = "This administrative account is restricted."
ADMINISTRATOR_REQUIRED = "Administrator access is required."
PERMISSION_REQUIRED = "You do not have permission to perform this action."
UNAVAILABLE = "Administrative authorization is temporarily unavailable."


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers=_BEARER)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail=detail)


def _unavailable() -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=UNAVAILABLE)


# ------------------------------------------------------------------ token

def bearer_token(authorization: str | None = Header(default=None)) -> str:
    """Extract the Supabase access token from 'Authorization: Bearer ...'."""
    if not authorization:
        raise _unauthorized("Authentication required.")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("A valid Bearer token is required.")
    return token.strip()


# ---------------------------------------------------------------- service

@lru_cache(maxsize=1)
def _default_service() -> AdminAccessService:
    return AdminAccessService()


def get_admin_access_service() -> AdminAccessService:
    """Overridable dependency. Misconfiguration fails closed with 503."""
    try:
        return _default_service()
    except AdminAccessUnavailableError as error:
        raise _unavailable() from error


# ----------------------------------------------------------------- access

async def current_admin_access(
    token: str = Depends(bearer_token),
    service: AdminAccessService = Depends(get_admin_access_service),
) -> AdminAccess:
    """The verified caller's access (may have no role). Does not authorize."""
    try:
        return await service.get_access(token)
    except AdminAuthenticationError as error:
        raise _unauthorized("Invalid or expired session.") from error
    except AdminAccessUnavailableError as error:
        raise _unavailable() from error


# Plain checks, usable outside FastAPI dependencies.

def is_administrator(access: AdminAccess) -> bool:
    return access.is_administrator


def is_admin_employee(access: AdminAccess) -> bool:
    return access.is_admin_employee


def is_active_admin_account(access: AdminAccess) -> bool:
    return access.has_admin_role and access.is_active


def get_effective_permissions(access: AdminAccess) -> frozenset[Permission]:
    return access.effective_permissions


def has_permission(access: AdminAccess, permission: Permission | str) -> bool:
    """Unknown permission strings are always denied."""
    return access.has_permission(permission)


def ensure_admin_account(access: AdminAccess) -> AdminAccess:
    if not access.has_admin_role:
        raise _forbidden(NO_ADMIN_ACCESS)
    if not access.is_active:
        raise _forbidden(RESTRICTED_ACCOUNT)
    return access


# ---------------------------------------------------------- dependencies

async def require_admin_account(
    access: AdminAccess = Depends(current_admin_access),
) -> AdminAccess:
    """Active Administrator or Admin Employee."""
    return ensure_admin_account(access)


async def require_administrator(
    access: AdminAccess = Depends(require_admin_account),
) -> AdminAccess:
    """Active Administrator only. Admin Employees never qualify."""
    if not access.is_administrator:
        raise _forbidden(ADMINISTRATOR_REQUIRED)
    return access


def require_permissions(
    *permissions: Permission | str,
) -> Callable[..., Awaitable[AdminAccess]]:
    """Dependency factory: the caller must hold every listed permission.

    Unregistered permission names are a programming error and raise at
    import time, so a typo can never create an unprotected route.
    """
    if not permissions:
        raise ValueError("require_permissions() needs at least one permission.")
    required: list[Permission] = []
    for item in permissions:
        parsed = parse_permission(item)
        if parsed is None:
            raise ValueError(f"Unknown administrative permission: {item!r}")
        required.append(parsed)
    frozen = tuple(required)

    async def dependency(
        access: AdminAccess = Depends(require_admin_account),
    ) -> AdminAccess:
        if not all(access.has_permission(p) for p in frozen):
            raise _forbidden(PERMISSION_REQUIRED)
        return access

    dependency.__name__ = "require_" + "_".join(p.value.replace(".", "_") for p in frozen)
    return dependency
