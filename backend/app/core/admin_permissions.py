"""Administrator roles, account statuses and the central permission registry.

This module is pure policy: it performs no I/O. Every administrative
permission check in the backend must use these constants instead of literal
strings. Anything not listed here (an unknown role, status or permission) is
denied.

Authority rules
- Administrator: every registered permission while the account is active.
- Admin Employee: only permissions explicitly assigned to the account AND
  listed in EMPLOYEE_ASSIGNABLE. Administrator-only permissions are ignored
  even if a database row assigns them.
- Anyone else (ordinary Google-authenticated users): no permissions.
- Suspended, banned or unknown account status: no permissions.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class AdminRole(StrEnum):
    ADMINISTRATOR = "administrator"
    ADMIN_EMPLOYEE = "admin_employee"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BANNED = "banned"


class Permission(StrEnum):
    # Organizations
    ORGANIZATIONS_VIEW = "organizations.view"
    ORGANIZATIONS_CREATE = "organizations.create"
    ORGANIZATIONS_EDIT = "organizations.edit"
    ORGANIZATIONS_ARCHIVE = "organizations.archive"
    ORGANIZATIONS_DOCUMENTS_UPLOAD = "organizations.documents.upload"
    ORGANIZATIONS_DOCUMENTS_VIEW = "organizations.documents.view"
    ORGANIZATIONS_PROFILES_GENERATE = "organizations.profiles.generate"
    ORGANIZATIONS_PROFILES_EDIT = "organizations.profiles.edit"
    ORGANIZATIONS_PROFILES_APPROVE = "organizations.profiles.approve"
    ORGANIZATIONS_PROFILES_REJECT = "organizations.profiles.reject"
    # Data Collection Agent
    AGENTS_COLLECTION_EXECUTE = "agents.collection.execute"
    AGENTS_COLLECTION_SCHEDULE = "agents.collection.schedule"
    AGENTS_COLLECTION_HISTORY = "agents.collection.history"
    # Data sources
    SOURCES_VIEW = "sources.view"
    SOURCES_MANAGE = "sources.manage"
    # Users and access
    USERS_VIEW = "users.view"
    USERS_EDIT = "users.edit"
    USERS_SUSPEND = "users.suspend"
    USERS_BAN = "users.ban"
    USERS_RESTORE = "users.restore"
    USERS_DELETE = "users.delete"
    ROLES_MANAGE = "roles.manage"
    PERMISSIONS_MANAGE = "permissions.manage"
    # Audit
    AUDIT_VIEW = "audit.view"


PERMISSION_DESCRIPTIONS: dict[Permission, str] = {
    Permission.ORGANIZATIONS_VIEW: "View organizations and approved organization profiles.",
    Permission.ORGANIZATIONS_CREATE: "Register new organizations.",
    Permission.ORGANIZATIONS_EDIT: "Edit organization registration details.",
    Permission.ORGANIZATIONS_ARCHIVE: "Archive and restore organizations.",
    Permission.ORGANIZATIONS_DOCUMENTS_UPLOAD: "Upload supporting documents for organizations.",
    Permission.ORGANIZATIONS_DOCUMENTS_VIEW: "View supporting documents for organizations.",
    Permission.ORGANIZATIONS_PROFILES_GENERATE: "Request AI-generated organization profile drafts.",
    Permission.ORGANIZATIONS_PROFILES_EDIT: "Edit organization profile drafts before review.",
    Permission.ORGANIZATIONS_PROFILES_APPROVE: "Approve a draft as the official organization profile.",
    Permission.ORGANIZATIONS_PROFILES_REJECT: "Reject an organization profile draft.",
    Permission.AGENTS_COLLECTION_EXECUTE: "Run the Data Collection Agent on demand.",
    Permission.AGENTS_COLLECTION_SCHEDULE: "Configure automatic collection schedules.",
    Permission.AGENTS_COLLECTION_HISTORY: "View Data Collection Agent runs and errors.",
    Permission.SOURCES_VIEW: "View the data source registry.",
    Permission.SOURCES_MANAGE: "Add, edit, enable, disable and remove data sources.",
    Permission.USERS_VIEW: "View user accounts.",
    Permission.USERS_EDIT: "Edit user account details.",
    Permission.USERS_SUSPEND: "Suspend user accounts.",
    Permission.USERS_BAN: "Ban user accounts.",
    Permission.USERS_RESTORE: "Restore suspended or banned accounts.",
    Permission.USERS_DELETE: "Delete user accounts.",
    Permission.ROLES_MANAGE: "Assign and remove administrative roles.",
    Permission.PERMISSIONS_MANAGE: "Assign and remove Admin Employee permissions.",
    Permission.AUDIT_VIEW: "View administrative audit logs.",
}

# Sensitive account management, access management and final approval
# decisions. Never effective for an Admin Employee.
ADMINISTRATOR_ONLY: frozenset[Permission] = frozenset({
    Permission.ORGANIZATIONS_PROFILES_APPROVE,
    Permission.ORGANIZATIONS_PROFILES_REJECT,
    Permission.USERS_EDIT,
    Permission.USERS_SUSPEND,
    Permission.USERS_BAN,
    Permission.USERS_RESTORE,
    Permission.USERS_DELETE,
    Permission.ROLES_MANAGE,
    Permission.PERMISSIONS_MANAGE,
})

ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

# Permissions an Administrator may assign to an Admin Employee.
EMPLOYEE_ASSIGNABLE: frozenset[Permission] = ALL_PERMISSIONS - ADMINISTRATOR_ONLY

# Import-time consistency guards: a registry mistake must stop the service
# rather than silently change who is allowed to do what.
if set(PERMISSION_DESCRIPTIONS) != set(ALL_PERMISSIONS):
    raise RuntimeError("Every administrative permission needs a description.")
if not ADMINISTRATOR_ONLY <= ALL_PERMISSIONS:
    raise RuntimeError("Administrator-only permissions must be registered permissions.")


def parse_role(value: object) -> AdminRole | None:
    """Return the matching role, or None for anything unknown."""
    try:
        return AdminRole(value) if isinstance(value, str) else None
    except ValueError:
        return None


def parse_status(value: object) -> AccountStatus | None:
    """Return the matching status, or None for anything unknown (denied)."""
    try:
        return AccountStatus(value) if isinstance(value, str) else None
    except ValueError:
        return None


def parse_permission(value: object) -> Permission | None:
    """Return the matching permission, or None for anything unknown (denied)."""
    try:
        return Permission(value) if isinstance(value, str) else None
    except ValueError:
        return None


def parse_permissions(values: Iterable[object]) -> frozenset[Permission]:
    """Registered permissions only; unknown values are dropped."""
    return frozenset(p for p in (parse_permission(v) for v in values) if p is not None)


def effective_permissions(
    role: AdminRole | None,
    status: AccountStatus | None,
    assigned: Iterable[Permission],
) -> frozenset[Permission]:
    """The permissions a user may actually exercise right now."""
    if status is not AccountStatus.ACTIVE:
        return frozenset()
    if role is AdminRole.ADMINISTRATOR:
        return ALL_PERMISSIONS
    if role is AdminRole.ADMIN_EMPLOYEE:
        return frozenset(assigned) & EMPLOYEE_ASSIGNABLE
    return frozenset()


def is_assignable_to_employee(permission: object) -> bool:
    parsed = parse_permission(permission)
    return parsed is not None and parsed in EMPLOYEE_ASSIGNABLE
