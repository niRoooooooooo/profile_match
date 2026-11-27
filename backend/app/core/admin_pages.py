"""Which Administrator UI files exist and who may open them.

This is the server-side source of truth for page access. It uses only the
central permission registry (app.core.admin_permissions); the browser receives
the computed result and never decides access itself.

Every file under /admin/ must be listed here. Anything not listed is never
served, so the URL space cannot be used to reach other files.
"""

from __future__ import annotations

from app.core.admin_permissions import Permission as P
from app.services.admin_access_service import AdminAccess

DEFAULT_PAGE = "overview.html"

# page -> permissions, any one of which grants access.
# An empty tuple means: any active Administrator or Admin Employee.
PAGES: dict[str, tuple[P, ...]] = {
    "overview.html": (),
    "user-management.html": (P.USERS_VIEW,),
    "roles-access.html": (P.ROLES_MANAGE, P.PERMISSIONS_MANAGE),
    "organizations.html": (P.ORGANIZATIONS_VIEW,),
    "organization-profile.html": (P.ORGANIZATIONS_VIEW,),
    "data-approvals.html": (P.ORGANIZATIONS_PROFILES_EDIT, P.ORGANIZATIONS_PROFILES_APPROVE,
                            P.ORGANIZATIONS_PROFILES_REJECT),
    "approval-review.html": (P.ORGANIZATIONS_PROFILES_EDIT, P.ORGANIZATIONS_PROFILES_APPROVE,
                             P.ORGANIZATIONS_PROFILES_REJECT),
    "agent-control.html": (P.AGENTS_COLLECTION_EXECUTE, P.AGENTS_COLLECTION_SCHEDULE,
                           P.AGENTS_COLLECTION_HISTORY),
    "data-sources.html": (P.SOURCES_VIEW,),
    "audit-logs.html": (P.AUDIT_VIEW,),
}

# Shared UI code and styles: any active administrative account. They contain
# no data; every page that uses them is permission-checked separately.
ASSETS: dict[str, str] = {
    "css/admin.css": "text/css; charset=utf-8",
    "js/admin.js": "text/javascript; charset=utf-8",
    "js/navigation.js": "text/javascript; charset=utf-8",
    "js/users.js": "text/javascript; charset=utf-8",
    "js/permissions.js": "text/javascript; charset=utf-8",
    "js/organizations.js": "text/javascript; charset=utf-8",
    "js/approvals.js": "text/javascript; charset=utf-8",
    "js/agents.js": "text/javascript; charset=utf-8",
    "js/sources.js": "text/javascript; charset=utf-8",
    "js/audit.js": "text/javascript; charset=utf-8",
}

# The old coming-soon index.html and the bare folder redirect (after
# authorization) to the dashboard; index.html itself is never served.
REDIRECTS = frozenset({"", "index.html"})


def can_open_page(access: AdminAccess, page: str) -> bool:
    if not (access.has_admin_role and access.is_active) or page not in PAGES:
        return False
    required = PAGES[page]
    return not required or any(access.has_permission(p) for p in required)


def page_access(access: AdminAccess) -> dict[str, bool]:
    return {page: can_open_page(access, page) for page in PAGES}
