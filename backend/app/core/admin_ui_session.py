"""Short-lived, opaque administrative UI sessions (in-memory registry).

Browser page navigation does not carry the Supabase Bearer token, so after
the server has verified a Bearer token and active administrative access it
issues a random session identifier in an HttpOnly cookie. Only a SHA-256 hash
of that identifier is kept here, together with the verified user UUID and the
Supabase access token used to re-check access on later requests. Nothing in
the cookie is trusted on its own: every protected request looks the session
up here, and access is re-verified with Supabase (see app.api.admin_ui).

Limits (single-process development registry)
- Sessions are lost when the server restarts (users simply re-open the page).
- Sessions are not shared between multiple worker processes or servers.
- The registry is bounded: MAX_SESSIONS in total, MAX_SESSIONS_PER_USER per
  user; the oldest sessions are evicted first.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.services.admin_access_service import AdminAccess

COOKIE_NAME = "pm_admin_ui"
COOKIE_PATH = "/admin"
SESSION_TTL_SECONDS = 15 * 60
# Phase 5.4.3A: there is no authorization reuse window. Every protected
# request (pages, assets and the session status) re-verifies access, and the
# session must still be live after that verification (see is_live).
MIN_REMAINING_SECONDS = 30
MAX_SESSIONS = 1000
MAX_SESSIONS_PER_USER = 5

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")   # secrets.token_urlsafe(32)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def token_expiry(access_token: str) -> float | None:
    """The JWT 'exp' claim, used only to cap the session lifetime.

    The token is NOT trusted because of this; Supabase Auth verifies it.
    """
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        return float(exp) if isinstance(exp, (int, float)) else None
    except (IndexError, ValueError, TypeError, AttributeError):
        return None


@dataclass
class AdminUISession:
    key: str
    user_id: str
    access_token: str = field(repr=False)
    created_at: float
    expires_at: float
    validated_at: float
    access: AdminAccess


class SessionNotCreated(Exception):
    """The Supabase session expires too soon to issue a UI session."""


class AdminUISessionStore:
    def __init__(
        self,
        *,
        ttl_seconds: int = SESSION_TTL_SECONDS,
        max_sessions: int = MAX_SESSIONS,
        max_per_user: int = MAX_SESSIONS_PER_USER,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_sessions
        self._max_per_user = max_per_user
        self._clock = clock
        self._sessions: dict[str, AdminUISession] = {}
        self._lock = threading.Lock()

    def now(self) -> float:
        return self._clock()

    def create(self, access: AdminAccess, access_token: str) -> tuple[str, AdminUISession]:
        """Issue a NEW random identifier (never reuses a client-supplied one)."""
        now = self._clock()
        token_exp = token_expiry(access_token)
        if token_exp is None:
            # The session must never outlive the token; unknown expiry -> refuse.
            raise SessionNotCreated("The sign-in session has no readable expiry.")
        expires_at = min(now + self._ttl, token_exp)
        if expires_at - now < MIN_REMAINING_SECONDS:
            raise SessionNotCreated("The sign-in session is about to expire.")

        raw = secrets.token_urlsafe(32)
        session = AdminUISession(key=_hash(raw), user_id=access.user_id, access_token=access_token,
                                 created_at=now, expires_at=expires_at, validated_at=now,
                                 access=access)
        with self._lock:
            self._purge_expired(now)
            own = sorted((s for s in self._sessions.values() if s.user_id == access.user_id),
                         key=lambda s: s.created_at)
            for old in own[: max(0, len(own) - self._max_per_user + 1)]:
                self._sessions.pop(old.key, None)
            if len(self._sessions) >= self._max:
                oldest = sorted(self._sessions.values(), key=lambda s: s.created_at)
                for old in oldest[: len(self._sessions) - self._max + 1]:
                    self._sessions.pop(old.key, None)
            self._sessions[session.key] = session
        return raw, session

    def get(self, raw: str | None) -> AdminUISession | None:
        """The live session for a cookie value, or None (unknown/expired/malformed)."""
        if not isinstance(raw, str) or not _ID_PATTERN.match(raw):
            return None
        key = _hash(raw)
        now = self._clock()
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return None
            if session.expires_at <= now:
                self._sessions.pop(key, None)
                return None
            return session

    def is_live(self, session: AdminUISession) -> bool:
        """Still this exact, unexpired session (not revoked or replaced).

        Checked AFTER the asynchronous re-verification, so a session revoked
        or expired while that check was running (logout, account switch,
        restriction found by a concurrent request) is never used to serve
        content.
        """
        with self._lock:
            return (self._sessions.get(session.key) is session
                    and session.expires_at > self._clock())

    def record_verification(self, session: AdminUISession, access) -> None:
        """Remember the latest verified access (information only, never reused
        for authorization)."""
        with self._lock:
            if self._sessions.get(session.key) is session:
                session.access = access
                session.validated_at = self._clock()

    def revoke(self, raw: str | None) -> bool:
        if not isinstance(raw, str) or not _ID_PATTERN.match(raw):
            return False
        return self.revoke_key(_hash(raw))

    def revoke_key(self, key: str) -> bool:
        with self._lock:
            return self._sessions.pop(key, None) is not None

    def revoke_user(self, user_id: str) -> int:
        with self._lock:
            keys = [k for k, s in self._sessions.items() if s.user_id == user_id]
            for k in keys:
                del self._sessions[k]
            return len(keys)

    def _purge_expired(self, now: float) -> None:
        for key in [k for k, s in self._sessions.items() if s.expires_at <= now]:
            del self._sessions[key]

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
