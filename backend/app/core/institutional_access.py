"""FastAPI dependencies for unified institutional authorization (Phase 5.3).

Not attached to any existing route in this phase. Future institutional routes
must depend on one of:

    require_active_account                 any verified, unrestricted user
    require_actor(Actor.X)                 active membership in actor X
    require_actor_head(Actor.X)            active Head of actor X
    require_institutional_permissions(...) every listed permission, each through
                                           a membership in its own actor

Administrator routes keep using app.core.admin_access (unchanged).

HTTP errors: 401 invalid/missing session; 403 restricted account or missing
institutional access; 503 authorization infrastructure unavailable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import lru_cache

from fastapi import Depends, HTTPException, status

from app.core.admin_access import bearer_token          # existing token extraction
from app.core.institutional_permissions import (
    InstitutionalPermission,
    parse_institutional_permission,
)
from app.core.institutional_roles import ACTOR_LABELS, Actor, parse_actor
from app.services.institutional_access_service import (
    AccessAuthenticationError,
    AccessUnavailableError,
    InstitutionalAccess,
    InstitutionalAccessService,
)

RESTRICTED_ACCOUNT = "This account is restricted."
UNAVAILABLE = "Authorization is temporarily unavailable."
PERMISSION_REQUIRED = "You do not have permission to perform this action."


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail=detail)


def _unavailable() -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=UNAVAILABLE)


@lru_cache(maxsize=1)
def _default_service() -> InstitutionalAccessService:
    return InstitutionalAccessService()


def get_institutional_access_service() -> InstitutionalAccessService:
    """Overridable dependency. Misconfiguration fails closed with 503."""
    try:
        return _default_service()
    except AccessUnavailableError as error:
        raise _unavailable() from error


async def current_institutional_access(
    token: str = Depends(bearer_token),
    service: InstitutionalAccessService = Depends(get_institutional_access_service),
) -> InstitutionalAccess:
    """The verified caller's unified access. Does not authorize by itself."""
    try:
        return await service.get_access(token)
    except AccessAuthenticationError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session.",
                            headers={"WWW-Authenticate": "Bearer"}) from error
    except AccessUnavailableError as error:
        raise _unavailable() from error


# Plain checks (usable outside FastAPI).

def can_access_actor(access: InstitutionalAccess, actor: Actor | str) -> bool:
    return access.can_access_actor(actor)


def is_actor_head(access: InstitutionalAccess, actor: Actor | str) -> bool:
    return access.is_head(actor)


def has_institutional_permission(access: InstitutionalAccess,
                                 permission: InstitutionalPermission | str) -> bool:
    """Unknown permissions are always denied."""
    return access.has_permission(permission)


def authorized_interfaces(access: InstitutionalAccess) -> list[str]:
    return [iface.id for iface, available in access.interfaces() if available]


# Dependencies.

async def require_active_account(
    access: InstitutionalAccess = Depends(current_institutional_access),
) -> InstitutionalAccess:
    if not access.account_active:
        raise _forbidden(RESTRICTED_ACCOUNT)
    return access


def _actor(value: Actor | str) -> Actor:
    parsed = value if isinstance(value, Actor) else parse_actor(value)
    if parsed is None:
        raise ValueError(f"Unknown institutional actor: {value!r}")
    return parsed


def require_actor(actor: Actor | str) -> Callable[..., Awaitable[InstitutionalAccess]]:
    """Active membership in `actor`. Unknown actors fail at definition time."""
    target = _actor(actor)

    async def dependency(access: InstitutionalAccess = Depends(require_active_account)):
        if not access.can_access_actor(target):
            raise _forbidden(f"{ACTOR_LABELS[target]} access is not available for this account.")
        return access

    dependency.__name__ = f"require_actor_{target.value}"
    return dependency


def require_actor_head(actor: Actor | str) -> Callable[..., Awaitable[InstitutionalAccess]]:
    """Active Head of `actor`. Employees and other actors' Heads never qualify."""
    target = _actor(actor)

    async def dependency(access: InstitutionalAccess = Depends(require_actor(target))):
        if not access.is_head(target):
            raise _forbidden(f"{ACTOR_LABELS[target]} Head access is required.")
        return access

    dependency.__name__ = f"require_head_{target.value}"
    return dependency


def require_institutional_permissions(
    *permissions: InstitutionalPermission | str,
) -> Callable[..., Awaitable[InstitutionalAccess]]:
    """Every listed permission, each held through its own actor's membership.

    Unregistered names raise at definition time, so a typo can never create an
    unprotected route.
    """
    if not permissions:
        raise ValueError("require_institutional_permissions() needs at least one permission.")
    required: list[InstitutionalPermission] = []
    for item in permissions:
        parsed = parse_institutional_permission(item)
        if parsed is None:
            raise ValueError(f"Unknown institutional permission: {item!r}")
        required.append(parsed)
    frozen = tuple(required)

    async def dependency(access: InstitutionalAccess = Depends(require_active_account)):
        if not all(access.has_permission(p) for p in frozen):
            raise _forbidden(PERMISSION_REQUIRED)
        return access

    dependency.__name__ = "require_" + "_".join(p.value.replace(".", "_") for p in frozen)
    return dependency
