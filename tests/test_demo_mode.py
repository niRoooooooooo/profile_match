"""Offline tests for CLOUD_PROCESSING_MODE=demo and the consent requirement.

The four checks before any document is sent to Gemini:
  1. demo mode explicitly enabled (else allowlist-only, as before);
  2. invention registered as public;
  3. every readable document starts with "FICTIONAL TEST DOCUMENT";
  4. innovator consent sent with the Generate request.
No live Gemini or Supabase calls are made.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _fixtures as fx
import test_workflow_offline as wf
from test_frontend_report import extract_function, inline_script

from app.agents import profiling_agent as agent
from app.services import cloud_authorization as auth
from app.services.cloud_authorization import CloudProcessingNotAuthorized
from app.services.document_parser import DocumentChunk, ParsedDocument, parse_document
from app.services.document_processor import ProcessedFile, ProcessingResult

BANNER = "FICTIONAL TEST DOCUMENT - Profile Match end-to-end test. Not a real invention."
CLEAN = {k: v for k, v in os.environ.items()
         if not k.startswith(("GEMINI_", "PROFILING_", "CLOUD_PROCESSING_"))}
DEMO = {**CLEAN, "CLOUD_PROCESSING_MODE": "demo"}
UPLOADS = Path(__file__).resolve().parent / "e2e_live" / "upload_files"


def processed(docs, confidentiality="public"):
    """docs: list of (filename, [chunk texts]) or (filename, None) for unreadable."""
    files = []
    for index, (name, chunks) in enumerate(docs):
        parsed = None if chunks is None else ParsedDocument(
            filename=name, file_type="pdf",
            chunks=[DocumentChunk(source_file=name, page=i + 1, text=t) for i, t in enumerate(chunks)])
        files.append(ProcessedFile(document_id=f"d{index}", filename=name, parsed=parsed,
                                   error=None if parsed else "unreadable"))
    return ProcessingResult(invention_id=fx.INVENTION_ID, owner_id=fx.OWNER_ID,
                            invention=fx.fictional_invention(confidentiality), documents=files)


MARKED = [(fx.RELEVANT, [f"{BANNER}\n\n{fx.PAGE_1}", fx.PAGE_2]),
          (fx.UNRELATED, [f"{BANNER}\n\n{fx.BAKERY}"])]
ONE_UNMARKED = [(fx.RELEVANT, [f"{BANNER}\n\n{fx.PAGE_1}", fx.PAGE_2]),
                (fx.UNRELATED, [fx.BAKERY])]


class FakeGemini:
    provider, model = "gemini", "gemini-3.5-flash-lite"

    def __init__(self):
        self.calls = 0

    def remaining_requests_today(self):
        return 100

    def generate_structured(self, prompt, response_model, **kwargs):
        self.calls += 1
        return response_model.model_validate_json(fx.comprehensive_json())


# ---------------------------------------------------------------------------
# 1-4: the authorization decision itself
# ---------------------------------------------------------------------------

class ModeTests(unittest.TestCase):
    def test_mode_parsing(self):
        for value, expected in ((None, "allowlist"), ("", "allowlist"), ("allowlist", "allowlist"),
                                ("demo", "demo"), (" DEMO ", "demo"), ("on", "invalid"),
                                ("production", "invalid")):
            env = dict(CLEAN) if value is None else {**CLEAN, "CLOUD_PROCESSING_MODE": value}
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(auth.processing_mode(), expected, value)

    def test_invalid_mode_blocks_even_allowlisted(self):
        env = {**CLEAN, "CLOUD_PROCESSING_MODE": "yes", "GEMINI_APPROVED_INVENTION_IDS": fx.INVENTION_ID}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(CloudProcessingNotAuthorized, "not recognised"):
                auth.authorize_cloud_processing(fx.fictional_invention(), processed(MARKED), True)

    def test_demo_mode_off_requires_allowlist(self):
        with mock.patch.dict(os.environ, CLEAN, clear=True):
            with self.assertRaisesRegex(CloudProcessingNotAuthorized, "administrator has approved"):
                auth.authorize_cloud_processing(fx.fictional_invention(), processed(MARKED), True)


@mock.patch.dict(os.environ, DEMO, clear=True)
class DemoChecksTests(unittest.TestCase):
    def authorize(self, docs=MARKED, confidentiality="public", consent=True, pass_docs=True):
        return auth.authorize_cloud_processing(
            fx.fictional_invention(confidentiality),
            processed(docs, confidentiality) if pass_docs else None, consent)

    def test_all_checks_pass(self):
        self.assertEqual(self.authorize(), "demo")

    def test_not_public_always_blocked(self):
        for level in ("restricted", "confidential", None, ""):
            with self.assertRaisesRegex(CloudProcessingNotAuthorized, "only inventions registered as public"):
                self.authorize(confidentiality=level)

    def test_consent_required(self):
        for consent in (False, None, "true", 1):
            with self.assertRaisesRegex(CloudProcessingNotAuthorized, "needs your confirmation"):
                self.authorize(consent=consent)

    def test_unmarked_document_blocks_and_is_named(self):
        with self.assertRaises(CloudProcessingNotAuthorized) as caught:
            self.authorize(docs=ONE_UNMARKED)
        self.assertIn(fx.UNRELATED, str(caught.exception))
        self.assertNotIn(fx.RELEVANT, str(caught.exception))
        self.assertIn("have not been changed", str(caught.exception))

    def test_documents_must_be_checked(self):
        with self.assertRaisesRegex(CloudProcessingNotAuthorized, "no readable documents"):
            self.authorize(pass_docs=False)
        with self.assertRaisesRegex(CloudProcessingNotAuthorized, "no readable documents"):
            self.authorize(docs=[(fx.RELEVANT, None)])

    def test_unreadable_documents_are_ignored_not_sent(self):
        self.assertEqual(self.authorize(docs=MARKED + [("scan.pdf", None)]), "demo")

    def test_allowlisted_invention_still_needs_public_and_consent(self):
        with mock.patch.dict(os.environ, {"GEMINI_APPROVED_INVENTION_IDS": fx.INVENTION_ID}):
            self.assertEqual(self.authorize(docs=ONE_UNMARKED), "allowlist")
            with self.assertRaises(CloudProcessingNotAuthorized):
                self.authorize(docs=ONE_UNMARKED, consent=False)
            with self.assertRaises(CloudProcessingNotAuthorized):
                self.authorize(docs=ONE_UNMARKED, confidentiality="restricted")


class MarkerPositionTests(unittest.TestCase):
    def parsed(self, *chunks):
        return ParsedDocument(filename="x.pdf", file_type="pdf",
                              chunks=[DocumentChunk(source_file="x.pdf", text=t) for t in chunks])

    def test_marker_at_start_accepted_case_and_spacing_tolerant(self):
        self.assertTrue(auth.has_fictional_marker(self.parsed("fictional  test\n document - x")))
        self.assertTrue(auth.has_fictional_marker(self.parsed("Title", BANNER + " body")))

    def test_marker_later_in_document_rejected(self):
        late = "Real confidential report. " * 20 + BANNER
        self.assertFalse(auth.has_fictional_marker(self.parsed(late)))
        self.assertFalse(auth.has_fictional_marker(self.parsed("A" * 400, BANNER)))

    def test_missing_or_partial_marker_rejected(self):
        for text in ("FICTIONAL TEST", "TEST DOCUMENT", "Fictitious test document", ""):
            self.assertFalse(auth.has_fictional_marker(self.parsed(text)), text)
        self.assertFalse(auth.has_fictional_marker(None))

    def test_generated_upload_files_pass_with_real_parser(self):
        files = sorted(UPLOADS.glob("*.*"))
        if not files:
            self.skipTest("run tests/e2e_live/make_documents.py first")
        for path in files:
            parsed = parse_document(path.read_bytes(), path.name)
            self.assertTrue(auth.has_fictional_marker(parsed), path.name)

    def test_unbannered_fixture_documents_fail(self):
        self.assertFalse(auth.has_fictional_marker(self.parsed(fx.PAGE_1)))


# ---------------------------------------------------------------------------
# Pipeline: no bypass, audit trail
# ---------------------------------------------------------------------------

@mock.patch.dict(os.environ, DEMO, clear=True)
class DemoPipelineTests(unittest.TestCase):
    def test_marked_documents_profiled_with_audit_note(self):
        client = FakeGemini()
        result = agent.build_profile_from_processed(
            processed(MARKED), ai_client=client, cloud_processing_consent=True)
        self.assertEqual(client.calls, 1)
        notes = [w for w in result.profile.quality_warnings if w.startswith("Cloud processing:")]
        self.assertEqual(len(notes), 1)
        self.assertIn("demo mode; innovator confirmed", notes[0])

    def test_injected_client_cannot_bypass_any_check(self):
        cases = [dict(docs=ONE_UNMARKED), dict(consent=False), dict(confidentiality="restricted")]
        for case in cases:
            client = FakeGemini()
            with self.assertRaises(CloudProcessingNotAuthorized):
                agent.build_profile_from_processed(
                    processed(case.get("docs", MARKED), case.get("confidentiality", "public")),
                    ai_client=client, cloud_processing_consent=case.get("consent", True))
            self.assertEqual(client.calls, 0, case)

    def test_default_consent_is_false(self):
        client = FakeGemini()
        with self.assertRaisesRegex(CloudProcessingNotAuthorized, "needs your confirmation"):
            agent.build_profile_from_processed(processed(MARKED), ai_client=client)
        self.assertEqual(client.calls, 0)


# ---------------------------------------------------------------------------
# API + fake Supabase (real routes, real parsing, no network)
# ---------------------------------------------------------------------------

MARKED_UPLOADS = [
    (wf.DOC_NAME, wf.docx_bytes(BANNER, fx.PAGE_1, fx.PAGE_2)),
    (wf.UNRELATED_NAME, wf.docx_bytes(BANNER, fx.BAKERY)),
]


class DemoApiTests(wf.WorkflowTestBase):
    allowlisted = False                     # no UUID editing needed
    extra_env = {"CLOUD_PROCESSING_MODE": "demo"}
    documents = MARKED_UPLOADS

    def assert_nothing_written(self):
        self.assertEqual(self.supabase.drafts, {})
        self.assertEqual(self.gemini.calls, 0)

    def test_generate_with_consent_succeeds_without_allowlist(self):
        response = self.call("POST", "/generate", json=wf.CONSENT)
        self.assertEqual(response.status_code, 200, response.text)
        warnings = response.json()["draft"]["edited_data"]["quality_warnings"]
        self.assertTrue(any(w.startswith("Cloud processing: demo mode") for w in warnings))
        self.assertEqual(self.gemini.calls, 1)

    def test_generate_without_consent_blocked(self):
        for kwargs in ({}, {"json": {}}, {"json": {"cloud_processing_consent": False}}):
            response = self.call("POST", "/generate", **kwargs)
            self.assertEqual(response.status_code, 403, kwargs)
            self.assertIn("needs your confirmation", response.json()["detail"])
        self.assert_nothing_written()

    def test_regenerate_also_requires_consent(self):
        draft = self.call("POST", "/generate", json=wf.CONSENT).json()["draft"]
        response = self.call("POST", "/regenerate", json={"expected_updated_at": draft["updated_at"]})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.supabase.drafts[fx.INVENTION_ID]["generation_number"], 1)

    def test_unknown_body_fields_rejected(self):
        response = self.call("POST", "/generate", json={"cloud_processing_consent": True, "x": 1})
        self.assertEqual(response.status_code, 422)
        self.assert_nothing_written()


class DemoApiUnmarkedTests(wf.WorkflowTestBase):
    allowlisted = False
    extra_env = {"CLOUD_PROCESSING_MODE": "demo"}
    documents = [MARKED_UPLOADS[0], (wf.UNRELATED_NAME, wf.docx_bytes(fx.BAKERY))]

    def test_real_style_document_blocks_generation(self):
        response = self.call("POST", "/generate", json=wf.CONSENT)
        self.assertEqual(response.status_code, 403)
        self.assertIn(wf.UNRELATED_NAME, response.json()["detail"])
        self.assertEqual(self.supabase.drafts, {})
        self.assertEqual(self.gemini.calls, 0)


class DemoApiRestrictedTests(wf.WorkflowTestBase):
    confidentiality = "restricted"
    allowlisted = False
    extra_env = {"CLOUD_PROCESSING_MODE": "demo"}
    documents = MARKED_UPLOADS

    def test_restricted_blocked_even_with_marker_and_consent(self):
        response = self.call("POST", "/generate", json=wf.CONSENT)
        self.assertEqual(response.status_code, 403)
        self.assertIn("only inventions registered as public", response.json()["detail"])
        self.assertEqual(self.gemini.calls, 0)


# ---------------------------------------------------------------------------
# Frontend consent dialog (real generate() code, run in Node.js)
# ---------------------------------------------------------------------------

@unittest.skipUnless(shutil.which("node"), "Node.js not installed")
class ConsentDialogTests(unittest.TestCase):
    def run_generate(self, confirm_answers, regenerate):
        program = r"""
let calls = [], answers = %s, asked = [];
const window = { confirm: msg => { asked.push(msg); return answers.shift(); } };
let selected = {id: 'inv-1'}, busy = false, draft = {updated_at: 'T1', generation_number: 1};
let workingProfile, editCounter, savedCounter, saveBlocked;
const draftLookup = new Map();
async function ensureSaved(){ return true; }
function busyState(){} function status(){} function renderInventions(){}
function renderEditor(){} function buttonVisibility(){}
async function api(method, endpoint, body){ calls.push({method, endpoint, body});
  return {draft: {updated_at: 'T2', generation_number: 2, edited_data: {}}}; }
%s
generate(%s).then(() => console.log(JSON.stringify({calls, asked})));
""" % (json.dumps(confirm_answers), "async " + extract_function(inline_script(), "generate"),
       "true" if regenerate else "false")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "g.js"
            path.write_text(program, encoding="utf-8")
            done = subprocess.run(["node", str(path)], capture_output=True, text=True,
                                  encoding="utf-8", timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_generate_sends_consent_after_confirmation(self):
        out = self.run_generate([True], regenerate=False)
        self.assertEqual(out["calls"], [{"method": "POST", "endpoint": "/api/inventions/inv-1/profile/generate",
                                         "body": {"cloud_processing_consent": True}}])
        self.assertIn("free Gemini API", out["asked"][0])
        self.assertIn("never for real, restricted or confidential", out["asked"][0])

    def test_cancelling_consent_sends_nothing(self):
        self.assertEqual(self.run_generate([False], regenerate=False)["calls"], [])

    def test_regenerate_keeps_its_warning_then_asks_consent(self):
        out = self.run_generate([True, True], regenerate=True)
        self.assertEqual(len(out["asked"]), 2)
        self.assertIn("replace your current editable draft", out["asked"][0])
        self.assertEqual(out["calls"][0]["body"],
                         {"expected_updated_at": "T1", "cloud_processing_consent": True})
        self.assertEqual(self.run_generate([True, False], regenerate=True)["calls"], [])


if __name__ == "__main__":
    unittest.main()
