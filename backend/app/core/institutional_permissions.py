"""Actor-scoped institutional permission registry (Phase 5.3).

Pure policy, no I/O. Every key is prefixed with its actor
("<actor>.<area>.<action>"), and a permission is only ever effective through
an active membership in THAT actor, so permissions cannot cross actor
boundaries. The 24 administrative permissions stay in
app.core.admin_permissions, unchanged; the two registries are disjoint.

Effective permissions of a membership
- Head: every permission of the actor (including Head-only ones).
- Employee: only permissions explicitly assigned AND listed as
  employee-assignable for that actor. Head-only and other actors'
  permissions are ignored even if a database row assigns them.
- Inactive membership, restricted account, unknown actor/position/status:
  nothing.

A permission existing here grants nothing by itself: routes must enforce it,
and functionality that is not implemented has no routes.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from app.core.admin_permissions import ALL_PERMISSIONS as ADMIN_PERMISSIONS
from app.core.institutional_roles import AccountStatus, Actor, MembershipStatus, Position


class InstitutionalPermission(StrEnum):
    # Innovation Center: invention profile verification, portfolio, matches
    IC_INVENTIONS_VIEW = "innovation_center.inventions.view"
    IC_PROFILES_REVIEW = "innovation_center.profiles.review"
    IC_PROFILES_REQUEST_CORRECTION = "innovation_center.profiles.request_correction"
    IC_PROFILES_APPROVE = "innovation_center.profiles.approve"
    IC_PROFILES_REJECT = "innovation_center.profiles.reject"
    IC_PORTFOLIO_VIEW = "innovation_center.portfolio.view"
    IC_MATCHES_VIEW = "innovation_center.matches.view"
    IC_MATCHES_REVIEW = "innovation_center.matches.review"
    IC_MATCHES_APPROVE = "innovation_center.matches.approve"
    IC_EMPLOYEES_VIEW = "innovation_center.employees.view"
    IC_REPORTS_VIEW = "innovation_center.reports.view"
    # Industry Liaison: partners, outreach, engagement
    IL_MATCHES_VIEW = "industry_liaison.matches.view"
    IL_PARTNERS_VIEW = "industry_liaison.partners.view"
    IL_OUTREACH_DRAFT = "industry_liaison.outreach.draft"
    IL_OUTREACH_REVIEW = "industry_liaison.outreach.review"
    IL_OUTREACH_APPROVE = "industry_liaison.outreach.approve"
    IL_OUTREACH_SEND = "industry_liaison.outreach.send"
    IL_ENGAGEMENT_VIEW = "industry_liaison.engagement.view"
    IL_ENGAGEMENT_UPDATE = "industry_liaison.engagement.update"
    IL_EMPLOYEES_VIEW = "industry_liaison.employees.view"
    IL_REPORTS_VIEW = "industry_liaison.reports.view"
    # Management: KPIs, trends, reports
    MG_OVERVIEW_VIEW = "management.overview.view"
    MG_PORTFOLIO_VIEW = "management.portfolio.view"
    MG_ANALYTICS_VIEW = "management.analytics.view"
    MG_REPORTS_VIEW = "management.reports.view"
    MG_REPORTS_EXPORT = "management.reports.export"
    MG_PERFORMANCE_VIEW = "management.performance.view"
    MG_EMPLOYEES_VIEW = "management.employees.view"
    # Industry Partner: none yet (architectural support only).


P = InstitutionalPermission

DESCRIPTIONS: dict[InstitutionalPermission, str] = {
    P.IC_INVENTIONS_VIEW: "View submitted inventions.",
    P.IC_PROFILES_REVIEW: "Review submitted invention profiles against evidence.",
    P.IC_PROFILES_REQUEST_CORRECTION: "Ask the innovator to correct or clarify a profile.",
    P.IC_PROFILES_APPROVE: "Give final institutional verification of an invention profile.",
    P.IC_PROFILES_REJECT: "Reject an invention profile.",
    P.IC_PORTFOLIO_VIEW: "View the institutional invention portfolio.",
    P.IC_MATCHES_VIEW: "View partner matches for inventions.",
    P.IC_MATCHES_REVIEW: "Review and comment on partner matches.",
    P.IC_MATCHES_APPROVE: "Approve matches for hand-over to Industry Liaison.",
    P.IC_EMPLOYEES_VIEW: "View Innovation Center staff.",
    P.IC_REPORTS_VIEW: "View Innovation Center reports.",
    P.IL_MATCHES_VIEW: "View approved partner matches.",
    P.IL_PARTNERS_VIEW: "View partner organizations and public business contacts.",
    P.IL_OUTREACH_DRAFT: "Draft outreach messages.",
    P.IL_OUTREACH_REVIEW: "Review outreach drafts.",
    P.IL_OUTREACH_APPROVE: "Approve outreach before it is sent.",
    P.IL_OUTREACH_SEND: "Send approved outreach to external organizations.",
    P.IL_ENGAGEMENT_VIEW: "View engagement timelines and meetings.",
    P.IL_ENGAGEMENT_UPDATE: "Record engagement events.",
    P.IL_EMPLOYEES_VIEW: "View Industry Liaison staff.",
    P.IL_REPORTS_VIEW: "View Industry Liaison reports.",
    P.MG_OVERVIEW_VIEW: "View the management overview and KPIs.",
    P.MG_PORTFOLIO_VIEW: "View the portfolio summary.",
    P.MG_ANALYTICS_VIEW: "View trends and analytics.",
    P.MG_REPORTS_VIEW: "View management reports.",
    P.MG_REPORTS_EXPORT: "Export management reports outside the system.",
    P.MG_PERFORMANCE_VIEW: "View staff and unit performance.",
    P.MG_EMPLOYEES_VIEW: "View Management staff.",
}

# Final institutional decisions, external communication, data export and
# staff oversight: Heads only, never assignable to Employees.
HEAD_ONLY: frozenset[InstitutionalPermission] = frozenset({
    P.IC_PROFILES_APPROVE, P.IC_PROFILES_REJECT, P.IC_MATCHES_APPROVE, P.IC_EMPLOYEES_VIEW,
    P.IL_OUTREACH_APPROVE, P.IL_OUTREACH_SEND, P.IL_EMPLOYEES_VIEW,
    P.MG_REPORTS_EXPORT, P.MG_PERFORMANCE_VIEW, P.MG_EMPLOYEES_VIEW,
})


def permission_actor(permission: InstitutionalPermission) -> Actor:
    return Actor(permission.value.split(".", 1)[0])


ACTOR_PERMISSIONS: dict[Actor, frozenset[InstitutionalPermission]] = {
    actor: frozenset(p for p in InstitutionalPermission if permission_actor(p) is actor)
    for actor in Actor
}
EMPLOYEE_ASSIGNABLE: dict[Actor, frozenset[InstitutionalPermission]] = {
    actor: perms - HEAD_ONLY for actor, perms in ACTOR_PERMISSIONS.items()
}
ALL_INSTITUTIONAL_PERMISSIONS: frozenset[InstitutionalPermission] = frozenset(InstitutionalPermission)

# Import-time guards: a registry mistake stops the service instead of
# silently changing who may do what.
if set(DESCRIPTIONS) != set(ALL_INSTITUTIONAL_PERMISSIONS):
    raise RuntimeError("Every institutional permission needs a description.")
if {p.value for p in ALL_INSTITUTIONAL_PERMISSIONS} & {p.value for p in ADMIN_PERMISSIONS}:
    raise RuntimeError("Institutional and administrative permission keys must not overlap.")
if ACTOR_PERMISSIONS[Actor.INDUSTRY_PARTNER]:
    raise RuntimeError("Industry Partner permissions are not defined in this phase.")


def parse_institutional_permission(value: object) -> InstitutionalPermission | None:
    """Registered permission, or None for anything unknown (denied)."""
    try:
        return InstitutionalPermission(value) if isinstance(value, str) else None
    except ValueError:
        return None


def assigned_for_actor(actor: Actor, values: Iterable[object]) -> tuple[frozenset[InstitutionalPermission], int]:
    """Registered permissions belonging to `actor`, and how many values were dropped."""
    values = list(values)
    kept = frozenset(p for p in map(parse_institutional_permission, values)
                     if p is not None and permission_actor(p) is actor)
    return kept, len(set(map(str, values))) - len(kept)


def effective_membership_permissions(
    actor: Actor,
    position: Position | None,
    membership_status: MembershipStatus | None,
    account_status: AccountStatus | None,
    assigned: Iterable[InstitutionalPermission],
) -> frozenset[InstitutionalPermission]:
    if account_status is not AccountStatus.ACTIVE or membership_status is not MembershipStatus.ACTIVE:
        return frozenset()
    if position is Position.HEAD:
        return ACTOR_PERMISSIONS[actor]
    if position is Position.EMPLOYEE:
        return frozenset(assigned) & EMPLOYEE_ASSIGNABLE[actor]
    return frozenset()


def is_assignable_to_employee(permission: object) -> bool:
    parsed = parse_institutional_permission(permission)
    return parsed is not None and parsed not in HEAD_ONLY
