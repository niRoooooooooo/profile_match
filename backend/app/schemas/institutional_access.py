"""Response schema for GET /api/access/me (Phase 5.3). Caller's own data only."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_FROZEN = ConfigDict(extra="forbid", frozen=True)


class AdministratorAccessInfo(BaseModel):
    model_config = _FROZEN
    role: Literal["administrator", "admin_employee"]
    account_status: Literal["active"]
    permissions: list[str] = Field(description="Effective administrative permissions, sorted.")


class MembershipInfo(BaseModel):
    model_config = _FROZEN
    actor: Literal["innovation_center", "industry_liaison", "management", "industry_partner"]
    actor_label: str
    position: Literal["head", "employee"]
    status: Literal["active"]
    permissions: list[str] = Field(description="Effective permissions of THIS actor only, sorted.")


class InterfaceInfo(BaseModel):
    model_config = _FROZEN
    id: str
    label: str
    href: str | None
    available: bool = Field(description="False: authorized but not implemented yet; grants nothing.")


class AccessMe(BaseModel):
    model_config = _FROZEN
    user_id: UUID = Field(description="Verified Supabase Auth user UUID of the caller.")
    account_status: Literal["active"] = Field(
        description="Only unrestricted accounts receive this response; restricted accounts get 403.")
    innovator: bool = Field(description="Default Innovator access.")
    administrator: AdministratorAccessInfo | None
    memberships: list[MembershipInfo] = Field(description="Active institutional memberships only.")
    interfaces: list[InterfaceInfo] = Field(description="Interfaces the frontend may offer, in order.")
