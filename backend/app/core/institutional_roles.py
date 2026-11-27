"""Institutional actors, positions, statuses and interfaces (Phase 5.3).

Pure policy, no I/O. Anything not listed here is denied.

- Every verified Google user is an Innovator by default while their
  application-wide account status is active.
- Institutional access exists only through an explicit, server-stored
  membership (one per actor) with a position: Head or Employee.
- Administrator authority is NOT defined here: it stays in the existing
  admin_accounts / admin_permissions / admin_permission_grants architecture
  (app.core.admin_permissions), unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# Application-wide account status uses the same values as administrative
# account status (active / suspended / banned).
from app.core.admin_permissions import AccountStatus

__all__ = ["AccountStatus", "Actor", "Position", "MembershipStatus", "Interface", "INTERFACES",
           "ACTOR_LABELS", "ACCEPTS_MEMBERSHIPS", "ACTOR_INTERFACE", "parse_actor",
           "parse_position", "parse_membership_status", "parse_account_status"]


class Actor(StrEnum):
    INNOVATION_CENTER = "innovation_center"
    INDUSTRY_LIAISON = "industry_liaison"
    MANAGEMENT = "management"
    INDUSTRY_PARTNER = "industry_partner"      # external; architectural support only


class Position(StrEnum):
    HEAD = "head"
    EMPLOYEE = "employee"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


ACTOR_LABELS: dict[Actor, str] = {
    Actor.INNOVATION_CENTER: "Innovation Center",
    Actor.INDUSTRY_LIAISON: "Industry Liaison",
    Actor.MANAGEMENT: "Management",
    Actor.INDUSTRY_PARTNER: "Industry Partner",
}

# Industry Partner memberships are not accepted until that actor is designed.
ACCEPTS_MEMBERSHIPS: frozenset[Actor] = frozenset({
    Actor.INNOVATION_CENTER, Actor.INDUSTRY_LIAISON, Actor.MANAGEMENT})


@dataclass(frozen=True)
class Interface:
    id: str
    label: str
    href: str | None
    implemented: bool


# Interfaces the frontend may offer. 'implemented' = a server-protected
# interface exists to open; an authorized but unimplemented interface is listed
# as unavailable and grants nothing. The Innovation Center is served only from
# its protected route (app.api.institutional_ui, Phase 5.4.1).
INTERFACES: dict[str, Interface] = {
    "innovator": Interface("innovator", "Innovator / Researcher", "/dashboard", True),
    "administrator": Interface("administrator", "Administrator", "/admin/overview.html", True),
    "innovation_center": Interface("innovation_center", "Innovation Center",
                                   "/institutional/innovation-center/overview.html", True),
    "industry_liaison": Interface("industry_liaison", "Industry Liaison", None, False),
    "management": Interface("management", "Management", None, False),
    "industry_partner": Interface("industry_partner", "Industry Partner", None, False),
}

ACTOR_INTERFACE: dict[Actor, str] = {actor: actor.value for actor in Actor}

if set(ACTOR_INTERFACE.values()) - set(INTERFACES):
    raise RuntimeError("Every actor needs an interface definition.")


def _parse(enum, value):
    try:
        return enum(value) if isinstance(value, str) else None
    except ValueError:
        return None


def parse_actor(value: object) -> Actor | None:
    return _parse(Actor, value)


def parse_position(value: object) -> Position | None:
    return _parse(Position, value)


def parse_membership_status(value: object) -> MembershipStatus | None:
    return _parse(MembershipStatus, value)


def parse_account_status(value: object) -> AccountStatus | None:
    return _parse(AccountStatus, value)
