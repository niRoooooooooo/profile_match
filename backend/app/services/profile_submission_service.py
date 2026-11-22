"""Create innovator-submitted report artifacts in private Supabase Storage.

This does NOT approve inventions for management. No existing document
bucket, invention row, or approved profile record is modified.
"""

import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from dotenv import load_dotenv
from pydantic import ValidationError

from app.schemas.profile import InventionAIProfile
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

SECTION_TITLES = {
    "identity": "Invention Overview",
    "problem_solution": "Problem and Solution",
    "technology": "Technology and Components",
    "applications": "Applications and Industries",
    "development": "Development and Validation",
    "readiness": "Technology Readiness",
    "intellectual_property": "Intellectual Property",
    "commercialization": "Commercialization",
    "partner_requirements": "Required Partner Capabilities",
    "gaps": "Research Gaps and Next Steps",
    "document_relevance": "Uploaded Document Relevance",
    "discrepancies": "Document Discrepancies",
    "missing_information": "Missing Information",
    "quality_warnings": "Processing and Evidence Warnings",
}


def nice_label(text: str) -> str:
    return str(text).replace("_", " ").strip().title()


def statement_text(value) -> str:
    if value is None:
        return "Not provided"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def add_field(doc: Document, label: str, value, *, depth: int = 0):
    """Render typed profile information without treating unverified edits as facts."""
    if isinstance(value, dict) and "classification" in value and "value" in value:
        p = doc.add_paragraph(style="Normal")
        p.paragraph_format.left_indent = Inches(min(depth, 3) * .16)
        p.add_run(f"{nice_label(label)}: ").bold = True
        p.add_run(statement_text(value.get("value")))
        classification = value.get("classification", "unknown")
        explanation = (value.get("explanation") or "").strip()
        marker = "Innovator-edited / unverified" if explanation.startswith("Innovator-edited") else nice_label(classification)
        meta = doc.add_paragraph(f"Status: {marker}")
        meta.style = "Caption"
        meta.paragraph_format.left_indent = Inches(min(depth, 3) * .16)
        if explanation and marker != "Innovator-edited / unverified":
            p2 = doc.add_paragraph(explanation); p2.style = "Caption"
        for ev in value.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            source = str(ev.get("source_file") or "Source")
            where = []
            if ev.get("page") is not None:
                where.append("page " + str(ev["page"]))
            if ev.get("section"):
                where.append("section " + str(ev["section"]))
            snippet = str(ev.get("excerpt") or "")[:500]
            cite = f"Evidence: {source}" + (" (" + ", ".join(where) + ")" if where else "")
            if snippet:
                cite += f" — {snippet}"
            p3 = doc.add_paragraph(cite); p3.style = "Caption"
        return
    if isinstance(value, dict):
        if depth > 0:
            doc.add_heading(nice_label(label), level=min(depth + 1, 4))
        for key, item in value.items():
            add_field(doc, key, item, depth=depth + 1)
    elif isinstance(value, list):
        if not value:
            doc.add_paragraph(f"{nice_label(label)}: No information supplied.")
        else:
            doc.add_heading(nice_label(label), level=min(depth + 2, 4))
            for index, item in enumerate(value, 1):
                if isinstance(item, (dict, list)):
                    if isinstance(item, dict) and "classification" in item and "value" in item:
                        add_field(doc, f"Item {index}", item, depth=depth + 1)
                    else:
                        add_field(doc, f"Item {index}", item, depth=depth + 1)
                else:
                    doc.add_paragraph(statement_text(item), style="List Bullet")
    else:
        p = doc.add_paragraph()
        p.add_run(nice_label(label) + ": ").bold = True
        p.add_run(statement_text(value))


def make_docx_bytes(manifest: dict) -> bytes:
    """Build a human-readable report. No cloud AI service is used."""
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(.8)
    section.bottom_margin = Inches(.75)
    section.left_margin = Inches(.8)
    section.right_margin = Inches(.8)
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10)
    normal.font.color.rgb = RGBColor(30, 42, 62)
    normal.paragraph_format.space_after = Pt(6)

    title = (manifest.get("profile", {}).get("identity", {}).get("title") or {}).get("value")
    heading = doc.add_heading("Invention Profiling Report", 0)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if title:
        p = doc.add_paragraph(title)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.style = "Subtitle"

    doc.add_paragraph("INNOVATOR-SUBMITTED · NOT MANAGEMENT-VERIFIED").runs[0].bold = True
    meta = doc.add_table(rows=0, cols=2)
    meta.style = "Table Grid"
    for k, v in (
        ("Invention ID", manifest["invention_id"]),
        ("Submission ID", manifest["submission_id"]),
        ("Submitted (UTC)", manifest["submitted_at"]),
        ("Qwen generation", manifest.get("generation_number")),
        ("Review status", "Innovator-submitted; pending future management review"),
    ):
        row = meta.add_row().cells
        row[0].text = k
        row[1].text = statement_text(v)

    doc.add_paragraph(
        "This report summarizes uploaded invention documents and the innovator's edits. "
        "Document statements, inferred applications, and innovator corrections are "
        "not independently verified. Refer to the original confidential files "
        "before relying on technical, legal, or commercial claims."
    )
    profile = manifest["profile"]
    for key, value in profile.items():
        doc.add_heading(SECTION_TITLES.get(key, nice_label(key)), level=1)
        if isinstance(value, dict):
            for field, child in value.items():
                add_field(doc, field, child)
        else:
            add_field(doc, key, value)
    footer = section.footer.paragraphs[0]
    footer.text = "Profile Match · Confidential invention profile · Innovator-submitted / unverified"
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


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

        paths = [prefix + "/profile.json", prefix + "/profile.docx"]
        uploaded = []
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
                try:
                    await self._upload(client, paths[0], json_bytes, JSON_MIME)
                    uploaded.append(paths[0])
                    await self._upload(client, paths[1], docx_bytes, DOCX_MIME)
                    uploaded.append(paths[1])
                except Exception:
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
