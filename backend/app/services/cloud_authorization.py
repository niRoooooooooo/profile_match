"""Decide whether an invention's documents may be sent to the Gemini API.

Free-tier Gemini requests may be used by Google to improve its products, so
being registered as public is NOT sufficient on its own. Every request needs:

1. invention.confidentiality == "public" (restricted/confidential: never);
2. explicit innovator consent at Generate time (cloud_processing_consent);
3. ONE of these server-side authorizations:
   a. ALLOWLIST: the invention ID is listed in GEMINI_APPROVED_INVENTION_IDS
      (comma-separated UUIDs maintained by the project administrator); or
   b. DEMO MODE: CLOUD_PROCESSING_MODE=demo is set on the server AND every
      readable document starts with the marker "FICTIONAL TEST DOCUMENT"
      (checked on the parsed text before any AI request).

Mode setting (CLOUD_PROCESSING_MODE): unset/"allowlist" = allowlist only
(previous behaviour); "demo" = allowlist OR marked fictional documents.
Any other value blocks all cloud processing.

Anything not authorized is blocked BEFORE any external request. Nothing is
changed: confidentiality is never modified; documents and drafts are untouched.
"""

import os
import re
from uuid import UUID

from app.services.gemini_client import GeminiClient


class CloudProcessingNotAuthorized(RuntimeError):
    """Profiling was blocked; safe to show to the innovator."""


FICTIONAL_MARKER = "FICTIONAL TEST DOCUMENT"
# The marker must appear at the very start of a document (banner position),
# so a real document that merely quotes the phrase later is not accepted.
MARKER_WINDOW_CHARACTERS = 300

_UNCHANGED = " Your uploaded documents and saved draft have not been changed."

BLOCKED_MESSAGE = (
    "AI profiling is not authorized for this invention. Cloud AI processing "
    "is only enabled for inventions registered as public that the project "
    "administrator has approved." + _UNCHANGED
)
NOT_PUBLIC_MESSAGE = (
    "AI profiling is not authorized: only inventions registered as public may "
    "be sent to the free Gemini API. Restricted and confidential inventions "
    "are never transmitted." + _UNCHANGED
)
CONSENT_REQUIRED_MESSAGE = (
    "AI profiling needs your confirmation that these documents may be sent "
    "to Google's free Gemini API. Click Generate again and confirm the "
    "dialog." + _UNCHANGED
)
INVALID_MODE_MESSAGE = (
    "AI profiling is disabled: the server's CLOUD_PROCESSING_MODE setting is "
    "not recognised." + _UNCHANGED
)
NO_DOCUMENTS_MESSAGE = (
    "AI profiling is not authorized: no readable documents could be checked "
    "for the fictional test marker." + _UNCHANGED
)


def _uuid(value) -> str | None:
    try:
        return str(UUID(str(value).strip()))
    except (TypeError, ValueError, AttributeError):
        return None


def approved_invention_ids() -> frozenset[str]:
    raw = os.getenv("GEMINI_APPROVED_INVENTION_IDS") or ""
    items = (_uuid(part) for part in raw.replace(";", ",").split(","))
    return frozenset(item for item in items if item)


def processing_mode() -> str:
    """'allowlist' (default), 'demo', or 'invalid'."""
    value = (os.getenv("CLOUD_PROCESSING_MODE") or "allowlist").strip().lower()
    return value if value in ("allowlist", "demo") else "invalid"


def _is_public(invention: dict) -> bool:
    return str(invention.get("confidentiality") or "").strip().lower() == "public"


def is_cloud_processing_authorized(invention: dict) -> bool:
    """Invention-level allowlist check (public AND allowlisted)."""
    invention_id = _uuid(invention.get("id"))
    return (
        _is_public(invention)
        and invention_id is not None
        and invention_id in approved_invention_ids()
    )


def has_fictional_marker(parsed) -> bool:
    """True if the document's first text starts with the fictional marker."""
    if parsed is None or not getattr(parsed, "chunks", None):
        return False
    opening = " ".join(chunk.text for chunk in parsed.chunks[:2])
    opening = re.sub(r"\s+", " ", opening).strip()[:MARKER_WINDOW_CHARACTERS]
    return FICTIONAL_MARKER.casefold() in opening.casefold()


def unmarked_documents(processed) -> tuple[list[str], int]:
    """(filenames of readable documents lacking the marker, readable count).

    Unreadable documents are never sent to the AI, so only readable ones
    need the marker.
    """
    readable = [
        item for item in processed.documents
        if item.parsed is not None and item.parsed.text.strip()
    ]
    missing = [item.filename for item in readable if not has_fictional_marker(item.parsed)]
    return missing, len(readable)


def authorize_cloud_processing(
    invention: dict,
    processed=None,
    consent: bool = False,
) -> str:
    """Raise CloudProcessingNotAuthorized unless every check passes.

    Returns the authorization basis ("allowlist" or "demo") for the audit
    note. In demo mode ``processed`` (the parsed documents) is required,
    because the marker is verified on the actual document text.
    """
    mode = processing_mode()
    if mode == "invalid":
        raise CloudProcessingNotAuthorized(INVALID_MODE_MESSAGE)
    if not _is_public(invention):
        raise CloudProcessingNotAuthorized(NOT_PUBLIC_MESSAGE)
    if consent is not True:
        raise CloudProcessingNotAuthorized(CONSENT_REQUIRED_MESSAGE)
    if is_cloud_processing_authorized(invention):
        return "allowlist"
    if mode == "demo":
        if processed is None:
            raise CloudProcessingNotAuthorized(NO_DOCUMENTS_MESSAGE)
        missing, readable = unmarked_documents(processed)
        if readable == 0:
            raise CloudProcessingNotAuthorized(NO_DOCUMENTS_MESSAGE)
        if missing:
            raise CloudProcessingNotAuthorized(
                "AI profiling is not authorized in demo mode: these documents "
                f"are not marked '{FICTIONAL_MARKER}' at the start: "
                f"{', '.join(sorted(missing))}. Demo mode only sends fictional "
                "test documents to the free Gemini API." + _UNCHANGED
            )
        return "demo"
    raise CloudProcessingNotAuthorized(BLOCKED_MESSAGE)


def create_profiling_client(
    invention: dict,
    processed=None,
    consent: bool = False,
) -> GeminiClient:
    """Return a Gemini client only for a fully authorized request."""
    authorize_cloud_processing(invention, processed, consent)
    return GeminiClient(confidentiality=invention.get("confidentiality"))
