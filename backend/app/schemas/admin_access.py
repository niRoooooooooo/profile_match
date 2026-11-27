"""Response schemas for administrative access endpoints."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AdminAccessMe(BaseModel):
    """The caller's own administrative identity. Contains no other user's data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: UUID = Field(description="Verified Supabase Auth user UUID of the caller.")
    role: Literal["administrator", "admin_employee"]
    account_status: Literal["active"] = Field(
        description="Only active accounts receive this response; restricted accounts get 403.")
    is_administrator: bool
    permissions: list[str] = Field(
        description="Effective permissions, sorted. Admin Employees never receive "
                    "Administrator-only permissions.")
