"""Schemas for the Administrator user directory (Phase 5.5.2).

They mirror exactly what public.admin_list_users() and
public.admin_get_user_details() (migration 006) return. Every model forbids
unknown fields, so an unexpected database response is rejected (HTTP 503)
instead of being passed through. Restriction reasons are not part of the
listing contract; in details they are only accepted for full Administrators
(enforced by the service).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_STRICT = ConfigDict(extra="forbid", frozen=True)

# Bounds identical to migration 006 (admin_list_users).
MAX_LIMIT = 100
MAX_OFFSET = 10000
MAX_SEARCH_LENGTH = 100
DEFAULT_LIMIT = 20

AccountStatusFilter = Literal["active", "suspended", "banned"]
AdminRoleFilter = Literal["administrator", "admin_employee", "none"]
PositionFilter = Literal["head", "employee"]


class DirectoryMembership(BaseModel):
    model_config = _STRICT

    actor: str = Field(min_length=1, max_length=100)
    position: Literal["head", "employee"]
    status: Literal["active", "suspended", "revoked"]


class DirectoryUser(BaseModel):
    model_config = _STRICT

    user_id: UUID
    email: str | None                      # nullable in auth.users
    full_name: str | None                  # NULL when no user_profiles row
    department: str | None
    registered_at: datetime | None         # auth.users.created_at (nullable)
    last_sign_in_at: datetime | None
    account_status: Literal["active", "suspended", "banned"]
    admin_role: Literal["administrator", "admin_employee"] | None
    admin_status: Literal["active", "suspended", "banned"] | None
    memberships: list[DirectoryMembership]


class _GrantList:
    """Helpers for validating explicit grant lists against the registries."""

    @staticmethod
    def administrative(values: list[str]) -> list[str]:
        from app.core.admin_permissions import ALL_PERMISSIONS
        known = {p.value for p in ALL_PERMISSIONS}
        if any(v not in known for v in values) or len(set(values)) != len(values):
            raise ValueError("unknown or duplicate administrative permission")
        return values

    @staticmethod
    def institutional(actor: str, values: list[str]) -> list[str]:
        from app.core.institutional_permissions import InstitutionalPermission
        known = {p.value for p in InstitutionalPermission}
        if (any(v not in known or not v.startswith(actor + ".") for v in values)
                or len(set(values)) != len(values)):
            raise ValueError("unknown, duplicate or cross-actor institutional permission")
        return values


class DetailAccount(BaseModel):
    model_config = _STRICT

    status: Literal["active", "suspended", "banned"]
    reason: str | None = Field(max_length=1000)       # full Administrators only
    changed_at: datetime | None                         # NULL when no status row


class DetailAdministrator(BaseModel):
    """Administrative account of the target. granted_permissions are the
    EXPLICIT grant rows only; an Administrator holds every administrative
    permission implicitly and normally has none."""

    model_config = _STRICT

    role: Literal["administrator", "admin_employee"]
    status: Literal["active", "suspended", "banned"]
    status_reason: str | None = Field(max_length=1000)  # full Administrators only
    status_changed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    granted_permissions: list[str]

    @field_validator("granted_permissions")
    @classmethod
    def _known_grants(cls, values: list[str]) -> list[str]:
        return _GrantList.administrative(values)


class DetailMembership(BaseModel):
    """Institutional membership. granted_permissions are EXPLICIT Employee
    grants only; a Head holds the actor's permissions implicitly."""

    model_config = _STRICT

    actor: str = Field(min_length=1, max_length=100)
    actor_label: str = Field(min_length=1, max_length=200)
    position: Literal["head", "employee"]
    status: Literal["active", "suspended", "revoked"]
    status_reason: str | None = Field(max_length=1000)  # full Administrators only
    created_at: datetime
    updated_at: datetime
    granted_permissions: list[str]

    @model_validator(mode="after")
    def _grants_belong_to_actor(self) -> "DetailMembership":
        _GrantList.institutional(self.actor, self.granted_permissions)
        return self


class UserDetails(BaseModel):
    """GET /api/admin/users/{user_id} response — exactly the jsonb object of
    public.admin_get_user_details() (migration 006)."""

    model_config = _STRICT

    user_id: UUID
    email: str | None
    full_name: str | None
    department: str | None
    has_profile: bool
    registered_at: datetime | None
    last_sign_in_at: datetime | None
    account: DetailAccount
    administrator: DetailAdministrator | None
    memberships: list[DetailMembership]
    owned_invention_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> "UserDetails":
        if not self.has_profile and (self.full_name is not None or self.department is not None):
            raise ValueError("profile fields present without a profile row")
        actors = [m.actor for m in self.memberships]
        if len(set(actors)) != len(actors):
            raise ValueError("duplicate membership actor")
        return self

    def contains_restriction_reasons(self) -> bool:
        return (self.account.reason is not None
                or (self.administrator is not None and self.administrator.status_reason is not None)
                or any(m.status_reason is not None for m in self.memberships))


class UserDirectoryPage(BaseModel):
    """GET /api/admin/users response. `total` counts every match, so a page
    past the end has users == [] with the correct total."""

    model_config = _STRICT

    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=MAX_LIMIT)
    offset: int = Field(ge=0, le=MAX_OFFSET)
    users: list[DirectoryUser]
