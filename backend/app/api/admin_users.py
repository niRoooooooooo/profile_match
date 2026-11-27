"""Administrator user directory API (Phase 5.5.2).

GET /api/admin/users
    Registered users from public.admin_list_users() (migration 006): paginated,
    filterable, literal case-insensitive search by name or email. Read-only.
GET /api/admin/users/{user_id}                                  (Phase 5.5.3)
    One target account from public.admin_get_user_details(). Read-only.
    404 when the account does not exist (SQLSTATE P0002); 422 for a malformed
    UUID.

Authorization (two independent layers)
1. FastAPI: require_permissions("users.view") — the existing administrative
   dependency (verified Bearer token, active administrative account,
   unrestricted application account, users.view held: Administrators
   implicitly, Admin Employees only by explicit grant).
2. Database: admin_list_users() re-checks the same rules through auth.uid(),
   because it is called with the caller's own token.
The caller's identity and permissions are never taken from the request.

Errors: 400 invalid directory query (SQLSTATE 22023); 401 missing/invalid/
expired session; 403 not permitted or restricted (incl. SQLSTATE 42501);
422 invalid request parameters; 503 Supabase unavailable or malformed
response. Every response carries Cache-Control: no-store.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.core.admin_access import bearer_token, require_permissions
from app.core.admin_permissions import Permission
from app.schemas.admin_users import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_OFFSET,
    MAX_SEARCH_LENGTH,
    AccountStatusFilter,
    AdminRoleFilter,
    PositionFilter,
    UserDetails,
    UserDirectoryPage,
)
from app.services.admin_access_service import (
    AdminAccess,
    AdminAccessUnavailableError,
    AdminAuthenticationError,
)
from app.services.admin_user_service import (
    AdminUserService,
    DirectoryForbiddenError,
    DirectoryInvalidArgumentError,
    DirectoryQuery,
    DirectoryUserNotFoundError,
)

router = APIRouter(prefix="/api/admin/users", tags=["Administrator User Directory"])

NO_STORE = {"Cache-Control": "no-store"}

# Service errors mapped to HTTP errors; anything else propagates unchanged.
_SERVICE_ERRORS = (AdminAuthenticationError, DirectoryForbiddenError, DirectoryInvalidArgumentError,
                   DirectoryUserNotFoundError, AdminAccessUnavailableError)

_ERRORS = {
    400: {"description": "Invalid directory query."},
    401: {"description": "Missing, invalid or expired session."},
    403: {"description": "users.view not held, or the account is restricted."},
    503: {"description": "User directory unavailable. Access is denied."},
}


@lru_cache(maxsize=1)
def _default_service() -> AdminUserService:
    return AdminUserService()


def get_admin_user_service() -> AdminUserService:
    """Overridable dependency. Misconfiguration fails closed with 503."""
    try:
        return _default_service()
    except AdminAccessUnavailableError as error:
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="User directory is temporarily unavailable.",
                            headers=NO_STORE)


@router.get("", response_model=UserDirectoryPage, responses=_ERRORS)
async def list_registered_users(
    response: Response,
    _access: Annotated[AdminAccess, Depends(require_permissions(Permission.USERS_VIEW))],
    token: Annotated[str, Depends(bearer_token)],
    service: Annotated[AdminUserService, Depends(get_admin_user_service)],
    search: Annotated[str | None, Query(max_length=MAX_SEARCH_LENGTH)] = None,
    account_status: AccountStatusFilter | None = None,
    admin_role: AdminRoleFilter | None = None,
    actor: Annotated[str | None, Query(min_length=1, max_length=100, pattern=r"^[a-z_]+$")] = None,
    position: PositionFilter | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET)] = 0,
) -> UserDirectoryPage:
    query = DirectoryQuery(search=search, account_status=account_status, admin_role=admin_role,
                           actor=actor, position=position, limit=limit, offset=offset)
    try:
        page = await service.list_users(token, query)
    except _SERVICE_ERRORS as error:
        raise _http_error(error) from error
    response.headers["Cache-Control"] = "no-store"
    return page


@router.get("/{user_id}", response_model=UserDetails,
            responses={**_ERRORS, 404: {"description": "The target account does not exist."}})
async def get_registered_user(
    user_id: UUID,
    response: Response,
    access: Annotated[AdminAccess, Depends(require_permissions(Permission.USERS_VIEW))],
    token: Annotated[str, Depends(bearer_token)],
    service: Annotated[AdminUserService, Depends(get_admin_user_service)],
) -> UserDetails:
    """Details of the TARGET account `user_id` (the caller is identified only by
    the verified Bearer token). Restriction reasons are returned only to full
    active Administrators; for anyone else they must be null (else 503)."""
    try:
        details = await service.get_user_details(
            token, user_id,
            caller_is_administrator=access.is_administrator and access.is_active)
    except _SERVICE_ERRORS as error:
        raise _http_error(error) from error
    response.headers["Cache-Control"] = "no-store"
    return details


def _http_error(error: Exception) -> Exception:
    """Map a service error to an HTTP error (always no-store, never raw details).

    Unknown errors are returned unchanged (and re-raised by the caller)."""
    if isinstance(error, AdminAuthenticationError):
        return HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session.",
                            headers={"WWW-Authenticate": "Bearer", **NO_STORE})
    if isinstance(error, DirectoryForbiddenError):
        return HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="You do not have permission to perform this action.",
                            headers=NO_STORE)
    if isinstance(error, DirectoryInvalidArgumentError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid directory query.",
                            headers=NO_STORE)
    if isinstance(error, DirectoryUserNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found.",
                            headers=NO_STORE)
    if isinstance(error, AdminAccessUnavailableError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="User directory is temporarily unavailable.",
                            headers=NO_STORE)
    return error
