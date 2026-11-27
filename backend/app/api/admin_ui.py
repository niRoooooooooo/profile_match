"""Protected Administrator UI (Phase 5.2.5).

Routes (all under /admin; the administrative UI cookie is scoped to /admin)

    POST   /admin/session         Bearer token -> new HttpOnly UI session cookie
    GET    /admin/session         the caller's role, status, permissions, pages
    DELETE /admin/session         revoke the UI session (logout)
    GET    /admin/                -> /admin/overview.html (after authorization)
    GET    /admin/<file>          allowlisted Administrator page or asset

Every /admin request is authorized BEFORE anything else: unauthorized callers
get 401/403/503 and a small page with no Administrator content, whatever the
path. Pages always re-verify the caller with Supabase; assets and the session
status may reuse a verification made within REVALIDATE_SECONDS. Only files
listed in app.core.admin_pages are ever served, straight from the
Administrator folder, so there is no path traversal surface. The public
/assets mount refuses the same folder (app.core.admin_static).
"""

from __future__ import annotations

import html
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from app.core.admin_access import bearer_token, get_admin_access_service
from app.core.admin_pages import ASSETS, DEFAULT_PAGE, PAGES, REDIRECTS, can_open_page, page_access
from app.core.admin_ui_session import (
    COOKIE_NAME,
    COOKIE_PATH,
    REVALIDATE_SECONDS,
    AdminUISession,
    AdminUISessionStore,
    SessionNotCreated,
)
from app.services.admin_access_service import (
    AdminAccess,
    AdminAccessService,
    AdminAccessUnavailableError,
    AdminAuthenticationError,
)

logger = logging.getLogger(__name__)

ADMIN_DIR = Path(__file__).resolve().parents[3] / "frontend" / "roles" / "administrator"
DEFAULT_URL = f"{COOKIE_PATH}/{DEFAULT_PAGE}"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})

SECURITY_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "Referrer-Policy": "same-origin",
}

MESSAGES = {
    "no_session": (401, "Administrator sign-in required",
                   "Your administrator session has not started or has expired."),
    "not_admin": (403, "Administrator access not available",
                  "Administrator access is not available for this account."),
    "restricted": (403, "Administrator access restricted",
                   "This administrative account is restricted."),
    "page_forbidden": (403, "Page not available for your role",
                       "Your administrative role does not include access to this page."),
    "unavailable": (503, "Administrator access temporarily unavailable",
                    "Administrative authorization is temporarily unavailable. Access is denied "
                    "until it can be checked."),
}

router = APIRouter(prefix=COOKIE_PATH, tags=["Administrator UI"])

_STORE = AdminUISessionStore()


def get_admin_ui_session_store() -> AdminUISessionStore:
    """Overridable dependency (single-process in-memory registry)."""
    return _STORE


class _Denied(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ----------------------------------------------------------------- helpers

def _same_origin(request: Request) -> bool:
    """State-changing session calls must come from this site's own pages."""
    site = request.headers.get("sec-fetch-site")
    if site is not None and site != "same-origin":
        return False
    origin = request.headers.get("origin")
    return bool(origin) and origin == f"{request.url.scheme}://{request.url.netloc}"


def _cookie_secure(request: Request) -> bool | None:
    """Secure cookie over HTTPS; plain HTTP only for local development."""
    if request.url.scheme == "https":
        return True
    if (request.url.hostname or "").lower() in LOCAL_HOSTS:
        return False
    return None


def _wants_html(request: Request, path: str) -> bool:
    return (path in PAGES or path in REDIRECTS or path.endswith(".html")
            or "text/html" in request.headers.get("accept", ""))


_GATE_SCRIPT = """
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<script src="/assets/js/api.js"></script>
<script>
(async () => {
  const msg = document.getElementById('gate-msg');
  const key = 'pmAdminGateAttempt';
  if (Date.now() - Number(sessionStorage.getItem(key) || 0) < 15000) {
    msg.textContent = 'Administrator access could not be started. Sign in again, then reopen the page.';
    return;
  }
  try {
    const client = await window.getSupabase();
    const {data} = await client.auth.getSession();
    const token = data && data.session && data.session.access_token;
    if (!token) { location.replace('/login'); return; }
    sessionStorage.setItem(key, String(Date.now()));
    msg.textContent = 'Checking administrator access…';
    const res = await fetch('/admin/session', {method: 'POST', credentials: 'same-origin',
      cache: 'no-store', headers: {Authorization: 'Bearer ' + token}});
    if (res.ok) { location.reload(); return; }
    msg.textContent = res.status === 403
      ? 'Administrator access is not available for this account.'
      : 'Administrator access could not be checked. Please try again later.';
  } catch (error) {
    msg.textContent = 'Administrator access could not be checked. Please try again later.';
  }
})();
</script>"""


def _gate_page(code: str) -> HTMLResponse:
    """A small page with NO Administrator content (no sidebar, data or code).

    For a missing/expired UI session it tries once to start one from the
    existing Supabase session; the token is sent only in an Authorization
    header, never in a URL.
    """
    status, title, text = MESSAGES[code]
    back = (f'<a class="btn" href="{DEFAULT_URL}">Administrator overview</a> '
            if code == "page_forbidden" else "")
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


def _denied(code: str, as_html: bool) -> Response:
    if as_html:
        return _gate_page(code)
    status, _, text = MESSAGES[code]
    return JSONResponse({"detail": text, "code": code}, status_code=status, headers=SECURITY_HEADERS)


async def _authorize(request: Request, store: AdminUISessionStore, service: AdminAccessService,
                     *, force: bool) -> tuple[AdminUISession, AdminAccess]:
    """Cookie -> server-side session -> (re)verified administrative access."""
    session = store.get(request.cookies.get(COOKIE_NAME))
    if session is None:
        raise _Denied("no_session")
    if not force and store.now() - session.validated_at < REVALIDATE_SECONDS:
        access = session.access
    else:
        try:
            access = await service.get_access(session.access_token)
        except AdminAuthenticationError as error:
            store.revoke_key(session.key)
            raise _Denied("no_session") from error
        except AdminAccessUnavailableError as error:
            store.mark_stale(session.key)       # no cached access after a failed check
            raise _Denied("unavailable") from error
        if access.user_id != session.user_id:
            store.revoke_key(session.key)
            raise _Denied("no_session")
        store.refresh(session.key, access)
    if not access.has_admin_role:
        store.revoke_user(session.user_id)
        raise _Denied("not_admin")
    if not access.is_active:
        store.revoke_user(session.user_id)
        raise _Denied("restricted")
    return session, access


# ---------------------------------------------------------------- session

@router.post("/session")
async def create_admin_ui_session(
    request: Request,
    authorization: str | None = Header(default=None),
    service: AdminAccessService = Depends(get_admin_access_service),
    store: AdminUISessionStore = Depends(get_admin_ui_session_store),
) -> Response:
    if not _same_origin(request):
        return JSONResponse({"detail": "Cross-origin requests are not allowed."},
                            status_code=403, headers=SECURITY_HEADERS)
    secure = _cookie_secure(request)
    if secure is None:
        return JSONResponse({"detail": "HTTPS is required for administrative sessions."},
                            status_code=400, headers=SECURITY_HEADERS)
    token = bearer_token(authorization)
    try:
        access = await service.get_access(token)
    except AdminAuthenticationError:
        return _denied("no_session", False)
    except AdminAccessUnavailableError:
        return _denied("unavailable", False)
    if not access.has_admin_role:
        return _denied("not_admin", False)
    if not access.is_active:
        return _denied("restricted", False)

    store.revoke(request.cookies.get(COOKIE_NAME))      # rotate: no session fixation
    try:
        raw, session = store.create(access, token)
    except SessionNotCreated:
        return _denied("no_session", False)

    response = JSONResponse({"redirect": DEFAULT_URL, "expires_at": int(session.expires_at)},
                            headers=SECURITY_HEADERS)
    response.set_cookie(COOKIE_NAME, raw, max_age=max(1, int(session.expires_at - store.now())),
                        path=COOKIE_PATH, secure=secure, httponly=True, samesite="strict")
    return response


@router.get("/session")
async def read_admin_ui_session(
    request: Request,
    store: AdminUISessionStore = Depends(get_admin_ui_session_store),
    service: AdminAccessService = Depends(get_admin_access_service),
) -> Response:
    try:
        session, access = await _authorize(request, store, service, force=False)
    except _Denied as denied:
        return _denied(denied.code, False)
    return JSONResponse({
        "role": access.role.value,
        "account_status": access.status.value,
        "is_administrator": access.is_administrator,
        "permissions": sorted(p.value for p in access.effective_permissions),
        "pages": page_access(access),
        "expires_at": int(session.expires_at),
    }, headers=SECURITY_HEADERS)


@router.delete("/session")
async def delete_admin_ui_session(
    request: Request,
    store: AdminUISessionStore = Depends(get_admin_ui_session_store),
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

async def _serve(request: Request, file_path: str, store: AdminUISessionStore,
                 service: AdminAccessService) -> Response:
    as_html = _wants_html(request, file_path)
    is_asset = file_path in ASSETS
    try:
        _, access = await _authorize(request, store, service, force=not is_asset)
    except _Denied as denied:
        return _denied(denied.code, as_html)

    if file_path in REDIRECTS:
        return RedirectResponse(DEFAULT_URL, status_code=303, headers=SECURITY_HEADERS)
    if file_path in PAGES:
        if not can_open_page(access, file_path):
            return _denied("page_forbidden", True)
        target, media_type = ADMIN_DIR / file_path, "text/html; charset=utf-8"
    elif is_asset:
        target, media_type = ADMIN_DIR / file_path, ASSETS[file_path]
    else:
        return JSONResponse({"detail": "Not found."}, status_code=404, headers=SECURITY_HEADERS)
    if not target.is_file():
        logger.warning("Allowlisted Administrator file is missing: %s", file_path)
        return JSONResponse({"detail": "Not found."}, status_code=404, headers=SECURITY_HEADERS)
    return FileResponse(target, media_type=media_type, headers=SECURITY_HEADERS)


@router.api_route("", methods=["GET", "HEAD"], include_in_schema=False)
async def admin_root(
    request: Request,
    store: AdminUISessionStore = Depends(get_admin_ui_session_store),
    service: AdminAccessService = Depends(get_admin_access_service),
) -> Response:
    return await _serve(request, "", store, service)


@router.api_route("/{file_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def admin_file(
    file_path: str,
    request: Request,
    store: AdminUISessionStore = Depends(get_admin_ui_session_store),
    service: AdminAccessService = Depends(get_admin_access_service),
) -> Response:
    return await _serve(request, file_path, store, service)
