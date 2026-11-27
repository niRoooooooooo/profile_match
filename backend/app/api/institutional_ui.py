"""Protected institutional UI (Phase 5.4.1).

Routes (all under /institutional; the institutional UI cookie is scoped there)

    POST   /institutional/session              Bearer token -> new HttpOnly UI session
    GET    /institutional/session              caller's institutional interfaces,
                                               positions, permissions and pages
    DELETE /institutional/session              revoke the UI session (logout)
    GET    /institutional/<actor>/             -> default page (after authorization)
    GET    /institutional/<actor>/<file>       allowlisted page or asset

Only implemented interfaces have routes (today: innovation-center); any other
actor path is a 404. Every request is authorized BEFORE anything else:
unauthorized callers get 401/403/503 and a small page with no institutional
content, whatever the path. Authorization comes only from the server:
the cookie points to a server-side session, and the caller's account status,
membership and permissions are re-read from Supabase (pages: every request;
assets and the session status: at most REVALIDATE_SECONDS old). Administrators
get no institutional access without an explicit membership.

This reuses the existing UI session store class and HTTP helpers of the
Administrator UI (separate registry, cookie name and path); the Administrator
session itself is unchanged.
"""

from __future__ import annotations

import html
import logging

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.api.admin_ui import SECURITY_HEADERS, _cookie_secure, _same_origin
from app.core.admin_access import bearer_token
from app.core.admin_ui_session import (
    REVALIDATE_SECONDS,
    AdminUISession,
    AdminUISessionStore,
    SessionNotCreated,
)
from app.core.institutional_access import get_institutional_access_service
from app.core.institutional_pages import (
    ACTOR_UIS,
    UI_BY_ACTOR,
    ActorUI,
    can_open,
    has_institutional_interface,
    page_access,
)
from app.core.institutional_roles import ACTOR_LABELS
from app.services.institutional_access_service import (
    AccessAuthenticationError,
    AccessUnavailableError,
    InstitutionalAccess,
    InstitutionalAccessService,
)

logger = logging.getLogger(__name__)

COOKIE_NAME = "pm_institutional_ui"
COOKIE_PATH = "/institutional"
SESSION_URL = f"{COOKIE_PATH}/session"

MESSAGES = {
    "no_session": (401, "Institutional sign-in required",
                   "Your institutional session has not started or has expired."),
    "not_member": (403, "Institutional access not available",
                   "This account does not have access to this institutional interface."),
    "restricted": (403, "Account restricted", "This account is restricted."),
    "page_forbidden": (403, "Page not available for your permissions",
                       "Your assigned permissions do not include this page."),
    "unavailable": (503, "Institutional access temporarily unavailable",
                    "Institutional authorization is temporarily unavailable. Access is denied "
                    "until it can be checked."),
}

router = APIRouter(prefix=COOKIE_PATH, tags=["Institutional UI"])

_STORE = AdminUISessionStore()          # separate registry from the Administrator UI


def get_institutional_ui_session_store() -> AdminUISessionStore:
    """Overridable dependency (single-process in-memory registry)."""
    return _STORE


class _Denied(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ----------------------------------------------------------------- helpers

def _wants_html(request: Request, ui: ActorUI | None, path: str) -> bool:
    item = ui.files.get(path) if ui else None
    return ((item is not None and item.is_page) or (ui is not None and path in ui.redirects)
            or path.endswith(".html") or "text/html" in request.headers.get("accept", ""))


_GATE_SCRIPT = """
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<script src="/assets/js/api.js"></script>
<script>
(async () => {
  const msg = document.getElementById('gate-msg');
  const key = 'pmInstitutionalGateAttempt';
  if (Date.now() - Number(sessionStorage.getItem(key) || 0) < 15000) {
    msg.textContent = 'Institutional access could not be started. Sign in again, then reopen the page.';
    return;
  }
  try {
    const client = await window.getSupabase();
    const {data} = await client.auth.getSession();
    const token = data && data.session && data.session.access_token;
    if (!token) { location.replace('/login'); return; }
    sessionStorage.setItem(key, String(Date.now()));
    msg.textContent = 'Checking institutional access...';
    const res = await fetch('""" + SESSION_URL + """', {method: 'POST', credentials: 'same-origin',
      cache: 'no-store', headers: {Authorization: 'Bearer ' + token}});
    if (res.ok) { location.reload(); return; }
    msg.textContent = res.status === 403
      ? 'Institutional access is not available for this account.'
      : 'Institutional access could not be checked. Please try again later.';
  } catch (error) {
    msg.textContent = 'Institutional access could not be checked. Please try again later.';
  }
})();
</script>"""


def _gate_page(code: str, ui: ActorUI | None = None) -> HTMLResponse:
    """A small page with NO institutional content (no navigation, data or code).

    For a missing/expired UI session it tries once to start one from the
    existing Supabase session; the token is sent only in an Authorization
    header, never in a URL.
    """
    status, title, text = MESSAGES[code]
    back = ""
    if code == "page_forbidden" and ui is not None:
        back = (f'<a class="btn" href="{ui.base_url}/{ui.default_page}">'
                f'{html.escape(ACTOR_LABELS[ui.actor])} overview</a> ')
    body = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>{html.escape(title)} | Profile Match</title>
<link rel="stylesheet" href="/assets/css/style.css">
</head><body>
<header class="top"><div class="brand">Partner Matching Agent</div></header>
<main class="content" style="max-width:640px">
<h1>{html.escape(title)}</h1>
<p id="gate-msg" role="status">{html.escape(text)}</p>
<p>{back}<a class="btn" href="/dashboard">Back to Innovator</a> <a class="btn" href="/login">Sign in</a></p>
</main>{_GATE_SCRIPT if code == "no_session" else ""}
</body></html>"""
    return HTMLResponse(body, status_code=status, headers=SECURITY_HEADERS)


def _denied(code: str, as_html: bool, ui: ActorUI | None = None) -> Response:
    if as_html:
        return _gate_page(code, ui)
    status, _, text = MESSAGES[code]
    return JSONResponse({"detail": text, "code": code}, status_code=status, headers=SECURITY_HEADERS)


def _not_found() -> Response:
    return JSONResponse({"detail": "Not found."}, status_code=404, headers=SECURITY_HEADERS)


async def _authorize(request: Request, store: AdminUISessionStore,
                     service: InstitutionalAccessService, *, force: bool
                     ) -> tuple[AdminUISession, InstitutionalAccess]:
    """Cookie -> server-side session -> (re)verified institutional access."""
    session = store.get(request.cookies.get(COOKIE_NAME))
    if session is None:
        raise _Denied("no_session")
    if not force and store.now() - session.validated_at < REVALIDATE_SECONDS:
        access: InstitutionalAccess = session.access          # type: ignore[assignment]
    else:
        try:
            access = await service.get_access(session.access_token)
        except AccessAuthenticationError as error:
            store.revoke_key(session.key)
            raise _Denied("no_session") from error
        except AccessUnavailableError as error:
            store.mark_stale(session.key)       # no cached access after a failed check
            raise _Denied("unavailable") from error
        if access.user_id != session.user_id:
            store.revoke_key(session.key)
            raise _Denied("no_session")
        store.refresh(session.key, access)      # type: ignore[arg-type]
    if not access.account_active:
        store.revoke_user(session.user_id)
        raise _Denied("restricted")
    if not has_institutional_interface(access):
        store.revoke_user(session.user_id)
        raise _Denied("not_member")
    return session, access


def _interfaces(access: InstitutionalAccess) -> list[dict]:
    return [{"id": iface.id, "label": iface.label, "href": iface.href}
            for iface, available in access.interfaces() if available and iface.href]


# ---------------------------------------------------------------- session

@router.post("/session")
async def create_institutional_ui_session(
    request: Request,
    authorization: str | None = Header(default=None),
    service: InstitutionalAccessService = Depends(get_institutional_access_service),
    store: AdminUISessionStore = Depends(get_institutional_ui_session_store),
) -> Response:
    if not _same_origin(request):
        return JSONResponse({"detail": "Cross-origin requests are not allowed."},
                            status_code=403, headers=SECURITY_HEADERS)
    secure = _cookie_secure(request)
    if secure is None:
        return JSONResponse({"detail": "HTTPS is required for institutional sessions."},
                            status_code=400, headers=SECURITY_HEADERS)
    token = bearer_token(authorization)
    try:
        access = await service.get_access(token)
    except AccessAuthenticationError:
        return _denied("no_session", False)
    except AccessUnavailableError:
        return _denied("unavailable", False)
    if not access.account_active:
        return _denied("restricted", False)
    if not has_institutional_interface(access):
        return _denied("not_member", False)

    store.revoke(request.cookies.get(COOKIE_NAME))      # rotate: no session fixation
    try:
        raw, session = store.create(access, token)       # type: ignore[arg-type]
    except SessionNotCreated:
        return _denied("no_session", False)

    first = next(ui for actor, ui in UI_BY_ACTOR.items() if access.can_access_actor(actor))
    response = JSONResponse({"redirect": f"{first.base_url}/{first.default_page}",
                             "expires_at": int(session.expires_at)}, headers=SECURITY_HEADERS)
    response.set_cookie(COOKIE_NAME, raw, max_age=max(1, int(session.expires_at - store.now())),
                        path=COOKIE_PATH, secure=secure, httponly=True, samesite="strict")
    return response


@router.get("/session")
async def read_institutional_ui_session(
    request: Request,
    store: AdminUISessionStore = Depends(get_institutional_ui_session_store),
    service: InstitutionalAccessService = Depends(get_institutional_access_service),
) -> Response:
    try:
        session, access = await _authorize(request, store, service, force=False)
    except _Denied as denied:
        return _denied(denied.code, False)
    actors = {}
    for actor, ui in UI_BY_ACTOR.items():
        membership = access.membership(actor)
        if membership is None:
            continue
        actors[actor.value] = {
            "label": ACTOR_LABELS[actor],
            "position": membership.position.value,
            "permissions": sorted(p.value for p in access.permissions(actor)),
            "pages": page_access(access, ui),
        }
    return JSONResponse({"user_id": access.user_id, "account_status": "active",
                         "interfaces": _interfaces(access), "actors": actors,
                         "expires_at": int(session.expires_at)}, headers=SECURITY_HEADERS)


@router.delete("/session")
async def delete_institutional_ui_session(
    request: Request,
    store: AdminUISessionStore = Depends(get_institutional_ui_session_store),
) -> Response:
    if not _same_origin(request):
        return JSONResponse({"detail": "Cross-origin requests are not allowed."},
                            status_code=403, headers=SECURITY_HEADERS)
    store.revoke(request.cookies.get(COOKIE_NAME))
    response = Response(status_code=204, headers=SECURITY_HEADERS)
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, secure=request.url.scheme == "https",
                           httponly=True, samesite="strict")
    return response


# ---------------------------------------------------------- pages/assets

def _render_page(ui: ActorUI, name: str, access: InstitutionalAccess) -> str:
    """The allowlisted page with server-computed access attached.

    Shared frontend files are referenced relatively in the source (so the pages
    still open offline from disk); they are rewritten to the public /assets
    URLs here. The data-interface-* attributes only let the page hide what the
    server would refuse anyway; they never grant anything.
    """
    text = (ui.directory / name).read_text(encoding="utf-8")
    text = text.replace('="../../css/', '="/assets/css/').replace('="../../js/', '="/assets/js/')
    membership = access.membership(ui.actor)
    pages = " ".join(page for page, ok in page_access(access, ui).items() if ok)
    permissions = " ".join(sorted(p.value for p in access.permissions(ui.actor)))
    attrs = (f'<body data-interface-position="{html.escape(membership.position.value)}" '
             f'data-interface-pages="{html.escape(pages)}" '
             f'data-interface-permissions="{html.escape(permissions)}" ')
    if text.count("<body ") != 1:
        raise RuntimeError(f"Unexpected page structure: {ui.slug}/{name}")
    return text.replace("<body ", attrs, 1)


async def _serve(request: Request, slug: str, file_path: str, store: AdminUISessionStore,
                 service: InstitutionalAccessService) -> Response:
    ui = ACTOR_UIS.get(slug)
    if ui is None:                       # unknown or not implemented: nothing exists here
        return _not_found()
    as_html = _wants_html(request, ui, file_path)
    item = ui.files.get(file_path)
    is_asset = item is not None and not item.is_page
    try:
        _, access = await _authorize(request, store, service, force=not is_asset)
    except _Denied as denied:
        return _denied(denied.code, as_html, ui)
    if not access.can_access_actor(ui.actor):
        return _denied("not_member", as_html, ui)

    if file_path in ui.redirects:
        return RedirectResponse(f"{ui.base_url}/{ui.default_page}", status_code=303,
                                headers=SECURITY_HEADERS)
    if item is None:
        return _not_found()
    if not can_open(access, ui, file_path):
        return _denied("page_forbidden", item.is_page, ui)
    target = ui.directory / file_path
    if not target.is_file():
        logger.warning("Allowlisted institutional file is missing: %s/%s", slug, file_path)
        return _not_found()
    if item.is_page:
        try:
            content = _render_page(ui, file_path, access)
        except (OSError, UnicodeDecodeError, RuntimeError):
            logger.exception("Institutional page could not be prepared: %s/%s", slug, file_path)
            return _not_found()
        return HTMLResponse(content, headers=SECURITY_HEADERS)
    return Response(target.read_bytes(), media_type=item.media_type, headers=SECURITY_HEADERS)


@router.api_route("/{slug}", methods=["GET", "HEAD"], include_in_schema=False)
async def institutional_root(
    slug: str,
    request: Request,
    store: AdminUISessionStore = Depends(get_institutional_ui_session_store),
    service: InstitutionalAccessService = Depends(get_institutional_access_service),
) -> Response:
    return await _serve(request, slug, "", store, service)


@router.api_route("/{slug}/{file_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def institutional_file(
    slug: str,
    file_path: str,
    request: Request,
    store: AdminUISessionStore = Depends(get_institutional_ui_session_store),
    service: InstitutionalAccessService = Depends(get_institutional_access_service),
) -> Response:
    return await _serve(request, slug, file_path, store, service)
