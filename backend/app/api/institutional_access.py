"""Unified access API (Phase 5.3).

GET /api/access/me
    The caller's own account status, default Innovator access, Administrator
    access (from the existing administrative authority), active institutional
    memberships with actor-scoped permissions, and authorized interfaces.
    Read-only: it accepts no actor, role or permission input.

NOT registered in app.main yet; registration needs a separate, approved change.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.core.institutional_access import require_active_account
from app.core.institutional_roles import ACTOR_LABELS
from app.schemas.institutional_access import (
    AccessMe,
    AdministratorAccessInfo,
    InterfaceInfo,
    MembershipInfo,
)
from app.services.institutional_access_service import InstitutionalAccess

router = APIRouter(prefix="/api/access", tags=["Institutional Access"])

_ERRORS = {
    401: {"description": "Missing, invalid or expired session."},
    403: {"description": "The account is restricted."},
    503: {"description": "Authorization is unavailable. Access is denied."},
}


@router.get("/me", response_model=AccessMe, responses=_ERRORS)
async def read_my_access(
    response: Response,
    access: InstitutionalAccess = Depends(require_active_account),
) -> AccessMe:
    response.headers["Cache-Control"] = "no-store"
    admin = None
    if access.administrator_access:
        admin = AdministratorAccessInfo(
            role=access.admin.role.value,
            account_status="active",
            permissions=sorted(p.value for p in access.admin.effective_permissions),
        )
    return AccessMe(
        user_id=access.user_id,
        account_status="active",
        innovator=access.innovator_access,
        administrator=admin,
        memberships=[
            MembershipInfo(actor=m.actor.value, actor_label=ACTOR_LABELS[m.actor],
                           position=m.position.value, status="active",
                           permissions=sorted(p.value for p in access.permissions(m.actor)))
            for m in access.active_memberships
        ],
        interfaces=[InterfaceInfo(id=i.id, label=i.label, href=i.href if ok else None, available=ok)
                    for i, ok in access.interfaces()],
    )
