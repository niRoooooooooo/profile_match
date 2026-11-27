"""Protected institutional UI files and who may open them (Phase 5.4.1).

Server-side source of truth for institutional page access. It uses only the
actor-scoped registry in app.core.institutional_permissions; the browser
receives the computed result and never decides access itself.

Only files listed here are ever served under /institutional/<actor>/; every
other path is a 404, so the URL space cannot reach other files (no traversal,
encoding, case or alias surface). The public /assets mount refuses the whole
frontend roles folder (see app.main).

Only the Innovation Center is implemented. Industry Liaison, Management and
Industry Partner have no protected routes until their modules exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.institutional_permissions import InstitutionalPermission as IP
from app.core.institutional_roles import Actor
from app.services.institutional_access_service import InstitutionalAccess

ROLES_DIR = Path(__file__).resolve().parents[3] / "frontend" / "roles"

HTML = "text/html; charset=utf-8"
CSS = "text/css; charset=utf-8"
JS = "text/javascript; charset=utf-8"


@dataclass(frozen=True)
class ProtectedFile:
    media_type: str
    # ALL of these permissions are required (dependencies included). Empty:
    # any active membership in the actor.
    requires: tuple[IP, ...] = ()

    @property
    def is_page(self) -> bool:
        return self.media_type == HTML


_APPROVALS = (IP.IC_INVENTIONS_VIEW, IP.IC_PROFILES_REVIEW)
_PORTFOLIO = (IP.IC_PORTFOLIO_VIEW,)
_MATCHES = (IP.IC_MATCHES_VIEW,)


@dataclass(frozen=True)
class ActorUI:
    actor: Actor
    slug: str                                  # URL segment and folder name
    directory: Path
    default_page: str
    files: dict[str, ProtectedFile]
    redirects: frozenset[str] = frozenset({"", "index.html"})

    @property
    def base_url(self) -> str:
        return f"/institutional/{self.slug}"

    def pages(self) -> tuple[str, ...]:
        return tuple(name for name, item in self.files.items() if item.is_page)


INNOVATION_CENTER_UI = ActorUI(
    actor=Actor.INNOVATION_CENTER,
    slug="innovation-center",
    directory=ROLES_DIR / "innovation-center",
    default_page="overview.html",
    files={
        # Pages. Overview sections are additionally filtered by permission.
        "overview.html": ProtectedFile(HTML),
        "profile-approvals.html": ProtectedFile(HTML, _APPROVALS),
        "portfolio.html": ProtectedFile(HTML, _PORTFOLIO),
        "match-review.html": ProtectedFile(HTML, _MATCHES),
        # Shared page code and styles (no records).
        "css/innovation-center.css": ProtectedFile(CSS),
        "js/shell.js": ProtectedFile(JS),
        "js/overview.js": ProtectedFile(JS),
        # Fictional demonstration data used by the pages.
        "js/data/mock-data.js": ProtectedFile(JS),
        "js/data/repository.js": ProtectedFile(JS),
        "js/data/sample-reports.js": ProtectedFile(JS, _APPROVALS),
        # Page-specific code: same permissions as its page.
        "js/profile-approvals.js": ProtectedFile(JS, _APPROVALS),
        "js/portfolio.js": ProtectedFile(JS, _PORTFOLIO),
        "js/match-review.js": ProtectedFile(JS, _MATCHES),
    },
)

# Implemented institutional interfaces, by URL slug.
ACTOR_UIS: dict[str, ActorUI] = {INNOVATION_CENTER_UI.slug: INNOVATION_CENTER_UI}
UI_BY_ACTOR: dict[Actor, ActorUI] = {ui.actor: ui for ui in ACTOR_UIS.values()}

for _ui in ACTOR_UIS.values():
    if _ui.default_page not in _ui.files or not _ui.files[_ui.default_page].is_page:
        raise RuntimeError(f"{_ui.slug}: the default page must be an allowlisted page.")
    if _ui.files[_ui.default_page].requires:
        raise RuntimeError(f"{_ui.slug}: the default page must open for every member.")
    for _name, _item in _ui.files.items():
        if any(not p.value.startswith(_ui.actor.value + ".") for p in _item.requires):
            raise RuntimeError(f"{_ui.slug}/{_name}: permissions must belong to the actor.")


def can_open(access: InstitutionalAccess, ui: ActorUI, name: str) -> bool:
    item = ui.files.get(name)
    if item is None or not access.can_access_actor(ui.actor):
        return False
    return all(access.has_permission(p) for p in item.requires)


def page_access(access: InstitutionalAccess, ui: ActorUI) -> dict[str, bool]:
    return {page: can_open(access, ui, page) for page in ui.pages()}


def has_institutional_interface(access: InstitutionalAccess) -> bool:
    """An active membership in at least one IMPLEMENTED institutional interface."""
    return any(access.can_access_actor(actor) for actor in UI_BY_ACTOR)
