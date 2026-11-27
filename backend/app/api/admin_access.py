"""Administrative access API (Phase 5.2).

GET /api/admin/access/me
    Returns the caller's own administrative role, account status and
    effective permissions. Ordinary users, restricted accounts and invalid
    sessions are denied. No other user's data is exposed.

This router is NOT registered in app.main yet; registration needs a separate,
approved change to main.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.core.admin_access import require_admin_account
from app.schemas.admin_access import AdminAccessMe
from app.services.admin_access_service import AdminAccess

router = APIRouter(prefix="/api/admin/access", tags=["Administrator Access"])

_ERRORS = {
    401: {"description": "Missing, invalid or expired session."},
    403: {"description": "No administrative role, or the administrative account is restricted."},
    503: {"description": "Administrative authorization is unavailable. Access is denied."},
}


@router.get("/me", response_model=AdminAccessMe, responses=_ERRORS)
async def read_my_admin_access(
    response: Response,
    access: AdminAccess = Depends(require_admin_account),
) -> AdminAccessMe:
    response.headers["Cache-Control"] = "no-store"
    return AdminAccessMe(
        user_id=access.user_id,
        role=access.role.value,
        account_status=access.status.value,
        is_administrator=access.is_administrator,
        permissions=sorted(p.value for p in access.effective_permissions),
    )
