"""Create innovator-submitted report artifacts in private Supabase Storage.

This does NOT approve inventions for management. No existing document
bucket, invention row, or approved profile record is modified.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from dotenv import load_dotenv
from pydantic import ValidationError

from app.core.account_status import ensure_active_account
from app.schemas.profile import InventionAIProfile
from app.services.report_docx import build_submission_docx
from app.services.profile_service import (
    ProfileService, ProfileServiceError, ProfileAccessError,
    ProfileConflictError,
)

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
BUCKET = "invention-profiles"  # Never confuse with source bucket: invention-document.
JSON_MIME = "application/json"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAX_BYTES = 10 * 1024 * 1024
SUBMISSION_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}$")

def make_docx_bytes(manifest: dict) -> bytes:
    """Build ONE consolidated, professional report from the saved edited draft.

    Uses the shared report renderer (the same one the web report uses), so
    the DOCX always matches the innovator's latest saved edits. No AI is used.
    """
    return build_submission_docx(manifest)


class ProfileSubmissionService:
    def __init__(self):
        self.profile_service = ProfileService()
        self.base_url = self.profile_service.supabase_url
        self.secret_key = self.profile_service.secret_key
        if not self.secret_key.startswith("sb_secret_"):
            raise ProfileServiceError("Backend Supabase secret key is missing.")

    def _headers(self, content_type: str | None = None) -> dict:
        # Modern sb_secret keys belong in apikey, NOT in a user's Authorization header.
        h = {"apikey": self.secret_key}
        if content_type:
            h["Content-Type"] = content_type
            h["x-upsert"] = "false"
        return h

    async def _upload(self, client: httpx.AsyncClient, path: str, data: bytes, mime: str):
        if len(data) > MAX_BYTES:
            raise ProfileServiceError("Generated report exceeds the 10 MB bucket limit.")
        url = f"{self.base_url}/storage/v1/object/{BUCKET}/{quote(path, safe='/')}"
        response = await client.post(url, headers=self._headers(mime), content=data)
        if response.status_code >= 400:
            raise ProfileServiceError(f"Private report Storage upload failed (HTTP {response.status_code}).")

    async def _delete_uploaded(self, client: httpx.AsyncClient, paths: list[str]):
        # Best-effort cleanup of our newly created paths only.
        if not paths:
            return
        try:
            await client.request(
                "DELETE",
                f"{self.base_url}/storage/v1/object/{BUCKET}",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"prefixes": paths},
            )
        except httpx.HTTPError:
            pass

    async def submit(self, invention_id: str, access_token: str, expected_updated_at: str):
        invention_id = str(UUID(str(invention_id)))
        owner_id = await self.profile_service._owner_id(invention_id, access_token)
        draft = await self.profile_service.get_draft(invention_id, access_token)
        if not draft:
            raise ProfileConflictError("Generate and save an AI draft before submitting.")
        if draft.get("updated_at") != expected_updated_at:
            raise ProfileConflictError("The draft was edited in another tab. Reload before submitting.")

        try:
            model = InventionAIProfile.model_validate(draft["edited_data"])
        except ValidationError as exc:
            raise ProfileServiceError("The saved profile has invalid structure.") from exc

        now = datetime.now(timezone.utc)
        submission_id = now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
        prefix = f"{owner_id}/{invention_id}/submissions/{submission_id}"
        manifest = {
            "schema_version": 1,
            "submission_id": submission_id,
            "invention_id": invention_id,
            "submitted_by": owner_id,
            "submitted_at": now.isoformat(),
            "review_status": "innovator_submitted_unverified",
            "generation_number": draft["generation_number"],
            "source_draft_updated_at": expected_updated_at,
            "profile": model.model_dump(mode="json"),
        }
        json_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        docx_bytes = make_docx_bytes(manifest)
        await self.profile_service._owner_id(invention_id, access_token)
        latest = await self.profile_service.get_draft(invention_id, access_token)
        if not latest or latest["updated_at"] != expected_updated_at:
            raise ProfileConflictError("The draft changed before submission. Reload and try again.")
        # Phase 5.4.3B.3: fresh account check before the first privileged
        # (secret-key) storage write. Restricted -> 403, nothing uploaded.
        await ensure_active_account(access_token, expected_user_id=owner_id)

        paths = [prefix + "/profile.json", prefix + "/profile.docx"]
        uploaded = []
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
                try:
                    await self._upload(client, paths[0], json_bytes, JSON_MIME)
                    uploaded.append(paths[0])
                    # Re-check before the upload that completes (publishes) the
                    # submission. On any failure, only THIS submission's new,
                    # uniquely named files are removed; earlier submissions live
                    # under other submission IDs and are never touched.
                    await ensure_active_account(access_token, expected_user_id=owner_id)
                    await self._upload(client, paths[1], docx_bytes, DOCX_MIME)
                    uploaded.append(paths[1])
                except BaseException:
                    await self._delete_uploaded(client, uploaded)
                    raise
        except httpx.HTTPError as error:
            raise ProfileServiceError("Supabase Storage could not be reached.") from error

        return {
            "status": "innovator_submitted_unverified",
            "invention_id": invention_id,
            "submission_id": submission_id,
            "submitted_at": manifest["submitted_at"],
            "bucket": BUCKET,
            "files": {"json": paths[0], "docx": paths[1]},
            "review_notice": "Not independently checked or management-approved.",
        }

    async def list_submissions(self, invention_id: str, access_token: str):
        invention_id = str(UUID(str(invention_id)))
        owner_id = await self.profile_service._owner_id(invention_id, access_token)
        prefix = f"{owner_id}/{invention_id}/submissions"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/storage/v1/object/list/{BUCKET}",
                    headers={**self._headers(), "Content-Type": "application/json"},
                    json={"prefix": prefix, "limit": 100, "offset": 0},
                )
                response.raise_for_status()
                entries = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise ProfileServiceError("Cannot list private report submissions.") from error
        if not isinstance(entries, list):
            raise ProfileServiceError("Unexpected report-list response.")
        submissions = sorted(
            [item["name"] for item in entries if isinstance(item, dict)
             and isinstance(item.get("name"), str)
             and SUBMISSION_PATTERN.fullmatch(item["name"])],
            reverse=True
        )
        return {"invention_id": invention_id, "submissions": submissions}

    async def get_report(self, invention_id: str, access_token: str, submission_id: str, format_: str):
        invention_id = str(UUID(str(invention_id)))
        owner_id = await self.profile_service._owner_id(invention_id, access_token)
        if not SUBMISSION_PATTERN.fullmatch(submission_id):
            raise ValueError("Invalid submission ID.")
        if format_ not in {"json", "docx"}:
            raise ValueError("Unsupported report format.")
        path = f"{owner_id}/{invention_id}/submissions/{submission_id}/profile.{format_}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/storage/v1/object/{BUCKET}/{quote(path, safe='/')}",
                    headers=self._headers()
                )
                if response.status_code == 404:
                    raise FileNotFoundError("Submitted report not found.")
                response.raise_for_status()
                if len(response.content) > MAX_BYTES:
                    raise ProfileServiceError("Stored report is unexpectedly large.")
                return response.content
        except httpx.HTTPError as error:
            raise ProfileServiceError("Failed to retrieve the private report.") from error
