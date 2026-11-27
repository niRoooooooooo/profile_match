"""Unified institutional access for the verified caller (Phase 5.3).

Composition, no duplication
1. The existing AdminAccessService verifies the Supabase access token (through
   the existing document_processor.verify_user) and returns the caller's
   Administrator access exactly as today. It remains the only source of
   Administrator authority.
2. The caller's institutional record is then read with the same token from
   the SECURITY DEFINER function public.institutional_get_my_access(), which
   returns only the caller's own application-wide account status and
   memberships (keyed on auth.uid()).

Nothing from the browser (Role Switcher, storage, request bodies, profile
metadata, user_profiles.role) is consulted. Missing tables or functions,
unreachable Supabase and malformed responses raise
AdminAccessUnavailableError (503); they never yield access.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from urllib.parse import urlparse
from uuid import UUID

import httpx

from app.config import SUPABASE_KEY, SUPABASE_URL
from app.core.institutional_permissions import (
    InstitutionalPermission,
    assigned_for_actor,
    effective_membership_permissions,
    parse_institutional_permission,
    permission_actor,
)
from app.core.institutional_roles import (
    ACCEPTS_MEMBERSHIPS,
    ACTOR_INTERFACE,
    INTERFACES,
    AccountStatus,
    Actor,
    Interface,
    MembershipStatus,
    Position,
    parse_account_status,
    parse_actor,
    parse_membership_status,
    parse_position,
)
from app.services.admin_access_service import (
    AdminAccess,
    AdminAccessService,
    AdminAccessUnavailableError,
    AdminAuthenticationError,
)

logger = logging.getLogger(__name__)

ACCESS_FUNCTION = "institutional_get_my_access"

# Same error types as the administrative layer: 401 / 503 semantics.
AccessAuthenticationError = AdminAuthenticationError
AccessUnavailableError = AdminAccessUnavailableError


@dataclass(frozen=True)
class Membership:
    actor: Actor
    position: Position
    status: MembershipStatus | None                 # None = unknown -> inactive
    assigned_permissions: frozenset[InstitutionalPermission] = field(default_factory=frozenset)

    @property
    def is_active(self) -> bool:
        return self.status is MembershipStatus.ACTIVE and self.actor in ACCEPTS_MEMBERSHIPS

    @property
    def is_head(self) -> bool:
        return self.position is Position.HEAD

    def effective_permissions(self, account_status: AccountStatus | None) -> frozenset[InstitutionalPermission]:
        if not self.is_active:
            return frozenset()
        return effective_membership_permissions(self.actor, self.position, self.status,
                                                account_status, self.assigned_permissions)


@dataclass(frozen=True)
class InstitutionalAccess:
    """The verified caller's unified access. Immutable."""

    user_id: str
    account_status: AccountStatus | None            # None = unknown -> restricted
    admin: AdminAccess
    memberships: tuple[Membership, ...] = ()

    @property
    def account_active(self) -> bool:
        return self.account_status is AccountStatus.ACTIVE

    @property
    def innovator_access(self) -> bool:
        return self.account_active

    @property
    def administrator_access(self) -> bool:
        """Existing Administrator authority, additionally blocked by an
        application-wide restriction."""
        return self.account_active and self.admin.has_admin_role and self.admin.is_active

    def membership(self, actor: Actor | str) -> Membership | None:
        """The caller's ACTIVE membership in `actor`, or None."""
        parsed = parse_actor(actor) if not isinstance(actor, Actor) else actor
        if parsed is None or not self.account_active:
            return None
        for item in self.memberships:
            if item.actor is parsed and item.is_active:
                return item
        return None

    @property
    def active_memberships(self) -> tuple[Membership, ...]:
        return tuple(m for m in self.memberships if self.membership(m.actor) is m)

    def can_access_actor(self, actor: Actor | str) -> bool:
        return self.membership(actor) is not None

    def is_head(self, actor: Actor | str) -> bool:
        item = self.membership(actor)
        return item is not None and item.is_head

    def permissions(self, actor: Actor | str) -> frozenset[InstitutionalPermission]:
        item = self.membership(actor)
        return item.effective_permissions(self.account_status) if item else frozenset()

    def has_permission(self, permission: InstitutionalPermission | str) -> bool:
        """Only through an active membership in the permission's own actor."""
        parsed = parse_institutional_permission(permission)
        return parsed is not None and parsed in self.permissions(permission_actor(parsed))

    def interfaces(self) -> list[tuple[Interface, bool]]:
        """Authorized interfaces as (interface, available) pairs, in menu order."""
        result: list[tuple[Interface, bool]] = []
        if self.innovator_access:
            result.append((INTERFACES["innovator"], True))
        for actor in (Actor.INNOVATION_CENTER, Actor.INDUSTRY_LIAISON, Actor.MANAGEMENT):
            if self.can_access_actor(actor):
                iface = INTERFACES[ACTOR_INTERFACE[actor]]
                result.append((iface, iface.implemented))
        if self.administrator_access:
            iface = INTERFACES["administrator"]
            if self.admin.is_admin_employee:
                iface = replace(iface, label="Admin Employee")
            result.append((iface, True))
        if self.can_access_actor(Actor.INDUSTRY_PARTNER):            # never today
            iface = INTERFACES["industry_partner"]
            result.append((iface, iface.implemented))
        return result


class InstitutionalAccessService:
    def __init__(
        self,
        admin_service: AdminAccessService | None = None,
        supabase_url: str | None = SUPABASE_URL,
        publishable_key: str | None = SUPABASE_KEY,
        *,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        url = (supabase_url or "").rstrip("/")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise AccessUnavailableError("Supabase URL must be a valid HTTPS URL.")
        if not publishable_key:
            raise AccessUnavailableError("Supabase publishable key is missing.")
        if publishable_key.startswith("sb_secret_"):
            raise AccessUnavailableError("A publishable key is required, not a secret key.")
        self._admin = admin_service or AdminAccessService(url, publishable_key, timeout=timeout,
                                                          transport=transport)
        self._url = url
        self._key = publishable_key
        self._timeout = httpx.Timeout(timeout, connect=min(timeout, 10.0))
        self._transport = transport

    async def get_access(self, access_token: str) -> InstitutionalAccess:
        # Verifies the token and returns existing Administrator access.
        admin = await self._admin.get_access(access_token)
        record = await self._fetch_own_record(access_token.strip())
        return self._interpret(admin, record)

    async def _fetch_own_record(self, token: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(
                    f"{self._url}/rest/v1/rpc/{ACCESS_FUNCTION}",
                    headers={"apikey": self._key, "Authorization": f"Bearer {token}",
                             "Accept": "application/json", "Content-Type": "application/json"},
                    json={},
                )
        except httpx.HTTPError as error:
            raise AccessUnavailableError("Authorization database is unreachable.") from error

        if response.status_code == 401:
            raise AccessAuthenticationError("Invalid or expired session.")
        if response.status_code >= 400:
            code = None
            try:
                body = response.json()
                code = body.get("code") if isinstance(body, dict) else None
            except ValueError:
                pass
            logger.warning("Institutional access lookup failed: HTTP %s, code %s",
                           response.status_code, code)
            raise AccessUnavailableError("Institutional authorization is not available.")
        try:
            data = response.json()
        except ValueError as error:
            raise AccessUnavailableError("Unexpected authorization response.") from error
        # The function always returns an object for the caller; anything else
        # (including null) means the infrastructure is not as expected.
        if not isinstance(data, dict):
            raise AccessUnavailableError("Unexpected authorization response.")
        return data

    @staticmethod
    def _interpret(admin: AdminAccess, record: dict) -> InstitutionalAccess:
        user_id = admin.user_id
        try:
            record_user = str(UUID(str(record.get("user_id"))))
        except (TypeError, ValueError) as error:
            raise AccessUnavailableError("Unexpected authorization response.") from error
        if record_user != user_id:
            raise AccessUnavailableError("Authorization record does not match the session.")

        raw_status = record.get("account_status")
        # No status row = never restricted = active. Unknown text = restricted.
        account_status = AccountStatus.ACTIVE if raw_status is None else parse_account_status(raw_status)

        raw_memberships = record.get("memberships")
        if not isinstance(raw_memberships, list):
            raise AccessUnavailableError("Unexpected authorization response.")

        memberships: list[Membership] = []
        seen: set[Actor] = set()
        for item in raw_memberships:
            if not isinstance(item, dict) or not isinstance(item.get("permissions", []), list):
                raise AccessUnavailableError("Unexpected authorization response.")
            actor = parse_actor(item.get("actor"))
            position = parse_position(item.get("position"))
            if actor is None or position is None:
                logger.warning("Ignored a membership with an unknown actor or position.")
                continue
            if actor in seen:                       # one membership per actor (DB unique key)
                raise AccessUnavailableError("Duplicate institutional membership.")
            seen.add(actor)
            assigned, dropped = assigned_for_actor(actor, item.get("permissions", []))
            if dropped:
                logger.warning("Ignored %d unknown or cross-actor permission value(s).", dropped)
            memberships.append(Membership(actor=actor, position=position,
                                          status=parse_membership_status(item.get("status")),
                                          assigned_permissions=assigned))

        return InstitutionalAccess(user_id=user_id, account_status=account_status, admin=admin,
                                   memberships=tuple(memberships))
