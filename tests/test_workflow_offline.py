"""Offline end-to-end workflow test with an in-memory FAKE Supabase.

Generate -> Review -> Edit -> Autosave -> Submit -> JSON/DOCX Storage -> Download

Nothing here touches the real Supabase project or Gemini:
- every httpx.AsyncClient is routed to FakeSupabase (unknown routes fail);
- DNS resolution is blocked, so an escaped request would raise;
- Supabase/Gemini credentials are replaced with fake values;
- the AI client is a fake returning a fixed fictional answer.
Only FICTIONAL Glowfern data is used.
"""

import copy
import io
import itertools
import json
import os
import socket
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from urllib.parse import unquote

import httpx
from docx import Document

import _fixtures as fx

from app.agents import profiling_agent as agent
from app.services import document_processor as dp

FAKE_URL = "https://fake-project.supabase.invalid"
FAKE_PUBLISHABLE = "sb_publishable_FAKE_FOR_TESTS"
FAKE_SECRET = "sb_secret_FAKE_FOR_TESTS"
OWNER_TOKEN = "owner-token"
OTHER_TOKEN = "other-user-token"
OTHER_USER = "44444444-4444-4444-8444-444444444444"
DOC_NAME = "glowfern_report.docx"
UNRELATED_NAME = "bakery_notes.docx"
SOURCE_BUCKET = "invention-document"
REPORT_BUCKET = "invention-profiles"
CONSENT = {"cloud_processing_consent": True}


def docx_bytes(*paragraphs) -> bytes:
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    stream = io.BytesIO()
    document.save(stream)
    return stream.getvalue()


def docx_text(data: bytes) -> str:
    document = Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        parts += [cell.text for row in table.rows for cell in row.cells]
    return "\n".join(parts)


class FakeSupabase:
    """Minimal PostgREST/Auth/Storage emulation with owner-only access (RLS)."""

    def __init__(self, invention, documents=None):
        self.users = {OWNER_TOKEN: fx.OWNER_ID, OTHER_TOKEN: OTHER_USER}
        self.inventions = {invention["id"]: dict(invention)}
        self.objects = {}
        self.document_rows = []
        self.drafts = {}
        self.requests = []
        self.unexpected = []
        self._clock = itertools.count(1)
        documents = documents or [
            (DOC_NAME, docx_bytes(fx.PAGE_1, fx.PAGE_2)),
            (UNRELATED_NAME, docx_bytes(fx.BAKERY)),
        ]
        for index, (name, data) in enumerate(documents):
            path = f"{fx.OWNER_ID}/{invention['id']}/{name}"
            self.objects[(SOURCE_BUCKET, path)] = data
            self.document_rows.append({
                "id": f"doc-{index}", "invention_id": invention["id"],
                "original_filename": name, "storage_path": path,
                "mime_type": "application/vnd.openxmlformats-officedocument."
                             "wordprocessingml.document",
                "file_size": len(data),
            })

    # ---------------------------------------------------------------- helpers
    def _now(self):
        base = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
        return (base + timedelta(seconds=next(self._clock))).isoformat()

    def _user(self, request):
        auth = request.headers.get("authorization", "")
        if request.headers.get("apikey") != FAKE_PUBLISHABLE or not auth.startswith("Bearer "):
            return None
        return self.users.get(auth[7:])

    def _is_backend(self, request):
        return (request.headers.get("apikey") == FAKE_SECRET
                and "authorization" not in request.headers)

    def _owns(self, user, invention_id):
        row = self.inventions.get(invention_id)
        return row is not None and row["owner_id"] == user

    @staticmethod
    def _eq(params, key):
        value = params.get(key)
        return value[3:] if value and value.startswith("eq.") else None

    @staticmethod
    def _json(status, payload):
        return httpx.Response(status, json=payload)

    # ---------------------------------------------------------------- routing
    def handler(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        params = dict(request.url.params)
        self.requests.append((request.method, path, params))
        user = self._user(request)
        backend = self._is_backend(request)

        if request.method == "GET" and path == "/auth/v1/user":
            return self._json(200, {"id": user}) if user else self._json(401, {})

        if path == "/rest/v1/inventions" and request.method == "GET" and user:
            rows = [r for r in self.inventions.values() if r["owner_id"] == user]
            if self._eq(params, "id"):
                rows = [r for r in rows if r["id"] == self._eq(params, "id")]
            if self._eq(params, "owner_id"):
                rows = [r for r in rows if r["owner_id"] == self._eq(params, "owner_id")]
            return self._json(200, rows)

        if path == "/rest/v1/invention_documents" and request.method == "GET" and user:
            invention_id = self._eq(params, "invention_id")
            rows = [r for r in self.document_rows
                    if r["invention_id"] == invention_id and self._owns(user, invention_id)]
            return self._json(200, rows)

        if path == "/rest/v1/invention_profile_drafts":
            invention_id = self._eq(params, "invention_id")
            if request.method == "GET" and user:
                row = self.drafts.get(invention_id)
                return self._json(200, [row] if row and self._owns(user, invention_id) else [])
            if request.method == "POST" and backend:
                body = json.loads(request.content)
                if body["invention_id"] in self.drafts:
                    return self._json(409, {"message": "duplicate"})
                now = self._now()
                row = {"id": f"draft-{len(self.drafts) + 1}", **body,
                       "created_at": now, "updated_at": now}
                self.drafts[body["invention_id"]] = row
                return self._json(201, [row])
            if request.method == "PATCH" and backend:
                row = self.drafts.get(invention_id)
                if not row or row["updated_at"] != self._eq(params, "updated_at"):
                    return self._json(200, [])
                row.update(json.loads(request.content))
                row["updated_at"] = self._now()
                return self._json(200, [row])

        prefix = f"/storage/v1/object/authenticated/{SOURCE_BUCKET}/"
        if request.method == "GET" and path.startswith(prefix) and user:
            object_path = path[len(prefix):]
            if object_path.split("/")[0] != user:
                return self._json(403, {})
            data = self.objects.get((SOURCE_BUCKET, object_path))
            return httpx.Response(200, content=data) if data else self._json(404, {})

        if path == f"/storage/v1/object/list/{REPORT_BUCKET}" and request.method == "POST" and backend:
            folder = json.loads(request.content)["prefix"].rstrip("/") + "/"
            names = sorted({key.split("/")[len(folder.split("/")) - 1]
                            for bucket, key in self.objects
                            if bucket == REPORT_BUCKET and key.startswith(folder)})
            return self._json(200, [{"name": name, "id": None} for name in names])

        prefix = f"/storage/v1/object/{REPORT_BUCKET}/"
        if path.startswith(prefix) and backend:
            object_path = path[len(prefix):]
            key = (REPORT_BUCKET, object_path)
            if request.method == "POST":
                if key in self.objects and request.headers.get("x-upsert") != "true":
                    return self._json(400, {"message": "exists"})
                self.objects[key] = request.content
                return self._json(200, {"Key": f"{REPORT_BUCKET}/{object_path}"})
            if request.method == "GET":
                data = self.objects.get(key)
                return httpx.Response(200, content=data) if data else self._json(404, {})

        if path == f"/storage/v1/object/{REPORT_BUCKET}" and request.method == "DELETE" and backend:
            for name in json.loads(request.content).get("prefixes", []):
                self.objects.pop((REPORT_BUCKET, name), None)
            return self._json(200, [])

        self.unexpected.append((request.method, path))
        return self._json(500, {"message": "unexpected route in fake Supabase"})


def flat_answer():
    """Fictional Gemini answer referencing the uploaded DOCX filenames."""
    payload = copy.deepcopy(fx.comprehensive_payload())
    rename = {fx.RELEVANT: DOC_NAME, fx.UNRELATED: UNRELATED_NAME}
    for entry in payload["document_relevance"]:
        entry["filename"] = rename[entry["filename"]]
    flat = fx.to_flat(payload)
    for claim in flat["claims"]:
        for evidence in claim.get("evidence", []):
            evidence["source_file"] = rename[evidence["source_file"]]
            evidence["page"] = None  # DOCX has no pages
    return json.dumps(flat)


class FakeGemini:
    provider = "gemini"
    model = "gemini-3.5-flash-lite"

    def __init__(self):
        self.calls = 0

    def remaining_requests_today(self):
        return 100

    def generate_structured(self, prompt, response_model, **kwargs):
        self.calls += 1
        if response_model.__name__ != "FlatProfileExtraction":
            return response_model()
        return response_model.model_validate_json(flat_answer())


class WorkflowTestBase(unittest.TestCase):
    confidentiality = "public"
    allowlisted = True       # put the fictional invention ID on the allowlist
    extra_env: dict = {}     # e.g. {"CLOUD_PROCESSING_MODE": "demo"}
    documents = None         # override the uploaded (name, bytes) documents

    def setUp(self):
        from fastapi.testclient import TestClient
        import app.main

        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("GEMINI_", "SUPABASE_", "CLOUD_PROCESSING_"))}
        env.update({
            "SUPABASE_URL": FAKE_URL,
            "SUPABASE_PUBLISHABLE_KEY": FAKE_PUBLISHABLE,
            "SUPABASE_SECRET_KEY": FAKE_SECRET,
        })
        if self.allowlisted:
            env["GEMINI_APPROVED_INVENTION_IDS"] = fx.INVENTION_ID
        env.update(self.extra_env)
        self.enterContext(mock.patch.dict(os.environ, env, clear=True))
        self.enterContext(mock.patch.object(dp, "SUPABASE_URL", FAKE_URL))
        self.enterContext(mock.patch.object(dp, "SUPABASE_KEY", FAKE_PUBLISHABLE))

        self.supabase = FakeSupabase(fx.fictional_invention(self.confidentiality), self.documents)
        real_async_client = httpx.AsyncClient

        def routed_client(*args, **kwargs):
            kwargs.pop("transport", None)
            return real_async_client(*args, transport=httpx.MockTransport(self.supabase.handler),
                                     **kwargs)

        self.enterContext(mock.patch("httpx.AsyncClient", routed_client))

        def no_network(*args, **kwargs):
            raise AssertionError("network access attempted during offline workflow test")

        # Any real Supabase/Google request needs DNS; block it. (Blocking
        # socket.connect would break asyncio's internal self-pipe on Windows.)
        self.enterContext(mock.patch.object(socket, "getaddrinfo", no_network))
        self.gemini = FakeGemini()
        self.enterContext(mock.patch.object(agent, "create_profiling_client",
                                            lambda invention, *args, **kwargs: self.gemini))
        self.client = TestClient(app.main.app)
        self.base = f"/api/inventions/{fx.INVENTION_ID}/profile"

    def tearDown(self):
        self.assertEqual(self.supabase.unexpected, [], "unexpected Supabase routes")

    def call(self, method, path, token=OWNER_TOKEN, **kwargs):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.request(method, self.base + path, headers=headers, **kwargs)


class FullWorkflowTests(WorkflowTestBase):
    def test_generate_review_edit_autosave_submit_store_download(self):
        sb = self.supabase

        # 1. Reopening before generation: nothing exists, no AI call.
        response = self.call("GET", "/draft")
        self.assertEqual((response.status_code, response.json()["status"]), (200, "not_generated"))
        self.assertEqual(self.gemini.calls, 0)

        # 2. Generate: real ownership check, real document download + parsing.
        response = self.call("POST", "/generate", json=CONSENT)
        self.assertEqual(response.status_code, 200, response.text)
        draft = response.json()["draft"]
        self.assertEqual(self.gemini.calls, 1)
        self.assertEqual(draft["generation_number"], 1)
        self.assertEqual(draft["ai_generated_data"], draft["edited_data"])
        profile = draft["edited_data"]
        self.assertEqual({c["value"] for c in profile["technology"]["components"]},
                         {"acrylic housing", "gel pad", "photodiode sensor", "ESP32 microcontroller"})
        self.assertTrue(all(c["classification"] == "document_fact"
                            for c in profile["technology"]["components"]))
        self.assertTrue(any(w.startswith("AI provider: Google Gemini (gemini-3.5-flash-lite)")
                            for w in profile["quality_warnings"]))
        relevance = {d["filename"]: d["relevance"] for d in profile["document_relevance"]}
        self.assertEqual(relevance, {DOC_NAME: "relevant", UNRELATED_NAME: "unrelated"})
        downloaded = [p for m, p, _ in sb.requests
                      if p.startswith(f"/storage/v1/object/authenticated/{SOURCE_BUCKET}/")]
        self.assertEqual(len(downloaded), 2)

        # 3. Generating again must not overwrite the draft.
        self.assertEqual(self.call("POST", "/generate", json=CONSENT).status_code, 409)
        self.assertEqual(self.gemini.calls, 1)

        # 4. Review: reopening loads the saved draft without running the AI.
        response = self.call("GET", "/draft")
        self.assertEqual(response.json()["status"], "draft_available")
        self.assertEqual(self.gemini.calls, 1)

        # 5. Edit + autosave exactly as the frontend editor does.
        edited = copy.deepcopy(profile)
        edited["development"]["prototype_status"] = {
            "value": "Prototype v2 glowed for 41 nights in the lab (innovator wording).",
            "classification": "inference", "evidence": [],
            "explanation": "Innovator-edited statement; not independently verified "
                           "against source documents.",
        }
        response = self.call("PUT", "/draft", json={
            "edited_data": edited, "expected_updated_at": draft["updated_at"]})
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()["draft"]
        self.assertNotEqual(saved["updated_at"], draft["updated_at"])
        self.assertEqual(saved["ai_generated_data"], draft["ai_generated_data"])  # original kept
        self.assertIn("innovator wording",
                      saved["edited_data"]["development"]["prototype_status"]["value"])

        # 6. Stale autosave (another tab) and schema-invalid edits are rejected.
        stale = self.call("PUT", "/draft", json={
            "edited_data": edited, "expected_updated_at": draft["updated_at"]})
        self.assertEqual(stale.status_code, 409)
        broken = copy.deepcopy(edited)
        broken["development"]["prototype_status"]["classification"] = "verified"
        invalid = self.call("PUT", "/draft", json={
            "edited_data": broken, "expected_updated_at": saved["updated_at"]})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(sb.drafts[fx.INVENTION_ID]["updated_at"], saved["updated_at"])

        # 7. Submit: a stale timestamp is refused and stores nothing.
        stale_submit = self.call("POST", "/submit",
                                 json={"expected_updated_at": draft["updated_at"]})
        self.assertEqual(stale_submit.status_code, 409)
        self.assertEqual([k for k in sb.objects if k[0] == REPORT_BUCKET], [])

        response = self.call("POST", "/submit", json={"expected_updated_at": saved["updated_at"]})
        self.assertEqual(response.status_code, 200, response.text)
        submission = response.json()
        self.assertEqual(submission["status"], "innovator_submitted_unverified")
        self.assertEqual(submission["bucket"], REPORT_BUCKET)
        sid = submission["submission_id"]
        prefix = f"{fx.OWNER_ID}/{fx.INVENTION_ID}/submissions/{sid}"
        self.assertEqual(submission["files"], {"json": f"{prefix}/profile.json",
                                               "docx": f"{prefix}/profile.docx"})

        # 8. Stored JSON: exactly the saved edited draft, marked unverified.
        stored_json = json.loads(sb.objects[(REPORT_BUCKET, f"{prefix}/profile.json")])
        self.assertEqual(stored_json["review_status"], "innovator_submitted_unverified")
        self.assertEqual(stored_json["profile"], saved["edited_data"])
        self.assertEqual(stored_json["generation_number"], 1)
        self.assertEqual(stored_json["submitted_by"], fx.OWNER_ID)

        # 9. Stored DOCX: readable, labelled, shows edits and UNVERIFIED notes.
        text = docx_text(sb.objects[(REPORT_BUCKET, f"{prefix}/profile.docx")])
        for expected in ("Invention Analysis Report", "INNOVATOR-SUBMITTED — NOT INSTITUTIONALLY APPROVED",
                         "Glowfern Bioluminescent Path Marker", "innovator wording",
                         "(Innovator-edited)", "AI generation", "Unverified",
                         "ESP32 microcontroller", "1. Executive Summary",
                         "8. Testing Methods and Experimental Results",
                         "15. Source Documents and References",
                         "Not documented in the uploaded materials."):
            self.assertIn(expected, text)
        self.assertNotIn("Qwen", text)
        self.assertNotIn("Item 1", text)  # no form-style item boxes

        # 10. List + download both files, byte-for-byte, private and no-store.
        listing = self.call("GET", "/submissions").json()
        self.assertEqual(listing["submissions"], [sid])
        for ext in ("json", "docx"):
            response = self.call("GET", f"/submissions/{sid}/{ext}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, sb.objects[(REPORT_BUCKET, f"{prefix}/profile.{ext}")])
            self.assertIn("attachment", response.headers["content-disposition"])
            self.assertEqual(response.headers["cache-control"], "private, no-store")

        # 11. Submission is not approval: no invention/table writes beyond drafts.
        writes = [(m, p) for m, p, _ in sb.requests if m in ("POST", "PATCH", "PUT", "DELETE")]
        allowed_paths = ("/rest/v1/invention_profile_drafts", f"/storage/v1/object/{REPORT_BUCKET}/",
                         f"/storage/v1/object/list/{REPORT_BUCKET}")
        self.assertTrue(all(p.startswith(allowed_paths) for _, p in writes), writes)
        self.assertEqual(sb.inventions[fx.INVENTION_ID]["status"], "registered")
        self.assertFalse(any(SOURCE_BUCKET in p and m != "GET" for m, p in writes))

    def test_regenerate_requires_current_timestamp_and_bumps_generation(self):
        first = self.call("POST", "/generate", json=CONSENT).json()["draft"]
        stale = self.call("POST", "/regenerate", json={"expected_updated_at": "2026-01-01T00:00:00+00:00", **CONSENT})
        self.assertEqual(stale.status_code, 409)
        response = self.call("POST", "/regenerate", json={"expected_updated_at": first["updated_at"], **CONSENT})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["draft"]["generation_number"], 2)
        self.assertEqual(self.gemini.calls, 2)

    def test_download_validation(self):
        self.assertEqual(self.call("GET", "/submissions/not-a-valid-id/json").status_code, 422)
        self.assertEqual(self.call("GET", "/submissions/20261124T120000Z-abcdef123456/pdf").status_code, 422)
        self.assertEqual(self.call("GET", "/submissions/20261124T120000Z-abcdef123456/json").status_code, 404)


class AccessControlTests(WorkflowTestBase):
    def test_missing_token_rejected_everywhere(self):
        for method, path, body in (("GET", "/draft", None), ("POST", "/generate", None),
                                   ("PUT", "/draft", {"edited_data": {}, "expected_updated_at": "x"}),
                                   ("POST", "/submit", {"expected_updated_at": "x"}),
                                   ("GET", "/submissions", None),
                                   ("GET", "/submissions/20261124T120000Z-abcdef123456/json", None)):
            response = self.call(method, path, token=None, json=body)
            self.assertEqual(response.status_code, 401, (method, path))
        self.assertEqual(self.gemini.calls, 0)

    def test_other_user_cannot_generate_read_or_submit(self):
        self.call("POST", "/generate", json=CONSENT)
        for method, path, body in (("GET", "/draft", None), ("POST", "/generate", CONSENT),
                                   ("POST", "/submit", {"expected_updated_at": "x"}),
                                   ("GET", "/submissions", None)):
            response = self.call(method, path, token=OTHER_TOKEN, json=body)
            self.assertEqual(response.status_code, 404, (method, path, response.text))
        self.assertEqual(self.gemini.calls, 1)


class BlockedInventionTests(WorkflowTestBase):
    confidentiality = "restricted"

    def test_restricted_invention_blocked_before_ai_and_nothing_written(self):
        response = self.call("POST", "/generate", json=CONSENT)
        self.assertEqual(response.status_code, 403)
        self.assertIn("not authorized", response.json()["detail"])
        self.assertEqual(self.gemini.calls, 0)
        self.assertEqual(self.supabase.drafts, {})
        self.assertEqual([k for k in self.supabase.objects if k[0] == REPORT_BUCKET], [])
        self.assertEqual(self.supabase.inventions[fx.INVENTION_ID]["confidentiality"], "restricted")


class FrontendContractTests(unittest.TestCase):
    """The report page calls exactly the backend routes exercised above."""

    def test_frontend_uses_tested_routes_and_payloads(self):
        from pathlib import Path
        html = (Path(__file__).resolve().parents[1] / "frontend" / "invention_report.html").read_text(
            encoding="utf-8")
        for snippet in ("/profile/draft`", "profile/${regenerate?'regenerate':'generate'}",
                        "{edited_data:snapshot,expected_updated_at:draft.updated_at}",
                        "/profile/submit`,{expected_updated_at:draft.updated_at}",
                        "/profile/submissions`", "/profile/submissions/${encodeURIComponent(submissionId)}/${ext}",
                        "Innovator-edited statement; not independently verified"):
            self.assertIn(snippet, html)


if __name__ == "__main__":
    unittest.main()
