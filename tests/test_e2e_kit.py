"""Offline tests for the live end-to-end kit in tests/e2e_live/ (no network)."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import _fixtures as fx

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e_live"))
import make_documents  # noqa: E402
import verify_downloads  # noqa: E402

from app.agents import profiling_agent as agent  # noqa: E402
from app.services.profile_submission_service import make_docx_bytes  # noqa: E402

PDF = "glowfern_technical_report.pdf"
IP = "glowfern_ip_disclosure.docx"


def f(field, value, source, excerpt, page=None, section=None):
    return {"field": field, "value": value, "classification": "document_fact",
            "evidence": [{"source_file": source, "page": page, "section": section,
                          "excerpt": excerpt}]}


def glowfern_answer():
    claims = [
        f("technology.components", "polycarbonate dome", PDF, "polycarbonate dome", 1),
        f("technology.components", "moisture-retaining hydrogel pad", PDF, "moisture-retaining hydrogel pad", 1),
        f("technology.components", "photodiode sensor", PDF, "photodiode sensor", 1),
        f("technology.components", "ESP32-C3 microcontroller", PDF, "ESP32-C3 microcontroller", 1),
        f("technology.components", "solar trickle charger", PDF, "solar trickle charger", 1),
        f("development.prototype_status", "Prototype v2 assembled in the university laboratory", PDF,
          "Prototype v2 was assembled in the university laboratory", 2),
        f("development.experimental_results", "Glowed for 41 consecutive nights", PDF,
          "glowed for 41 consecutive nights", 2),
        f("development.experimental_results", "Average luminance of 0.8 cd/m2", PDF,
          "average luminance of 0.8 cd/m2", 2),
        f("development.experimental_results", "Survived 72 hours at 85% relative humidity", PDF,
          "survived 72 hours at 85% relative humidity", 2),
        f("development.technical_limitations", "Brightness dropped by 30% below 10 degrees Celsius", PDF,
          "Brightness dropped by 30% below 10 degrees Celsius", 3),
        f("development.technical_limitations", "No field validation has been performed", PDF,
          "No field validation has been performed", 3),
        f("intellectual_property.patent_status", "A provisional patent application was filed on 3 March 2026",
          IP, "A provisional patent application was filed on 3 March 2026", section="Intellectual property"),
        f("commercialization.documented_costs", "Estimated unit cost is USD 14 at 1,000 units", IP,
          "The estimated unit cost is USD 14", section="Costs"),
    ]
    return json.dumps({
        "document_relevance": [
            {"filename": PDF, "relevance": "relevant", "explanation": "Technical report."},
            {"filename": IP, "relevance": "relevant", "explanation": "IP disclosure."},
            {"filename": "bakery_notes.docx", "relevance": "unrelated", "explanation": "Bakery."},
        ],
        "claims": claims,
    })


class FakeGemini:
    provider, model = "gemini", "gemini-3.5-flash-lite"

    def remaining_requests_today(self):
        return 100

    def generate_structured(self, prompt, response_model, **kwargs):
        if response_model.__name__ == "FlatProfileExtraction":
            return response_model.model_validate_json(glowfern_answer())
        return response_model()


class MakeDocumentsTests(unittest.TestCase):
    def test_generates_three_parseable_fictional_files(self):
        with redirect_stdout(io.StringIO()) as out:
            make_documents.main()
        report = out.getvalue()
        self.assertEqual(report.count("parse check: OK"), 3, report)
        for name in (PDF, IP, "bakery_notes.docx"):
            self.assertTrue((make_documents.OUT / name).is_file())
        self.assertIn("3 pages", report)


@mock.patch.dict(os.environ, {"GEMINI_APPROVED_INVENTION_IDS": fx.INVENTION_ID})
class VerifyDownloadsTests(unittest.TestCase):
    def submission(self, edited=True):
        processed = fx.comparison_processed_result()
        result = agent.build_profile_from_processed(cloud_processing_consent=True, processed=processed, ai_client=FakeGemini())
        profile = result.profile.model_dump(mode="json")
        if edited:
            profile["development"]["prototype_status"] = {
                "value": "Prototype v2 (E2E innovator edit)", "classification": "inference",
                "evidence": [], "explanation": "Innovator-edited statement; not independently "
                                               "verified against source documents."}
        manifest = {"schema_version": 1, "submission_id": "20261124T120000Z-abcdef123456",
                    "invention_id": fx.INVENTION_ID, "submitted_by": fx.OWNER_ID,
                    "submitted_at": "2026-11-24T12:00:00+00:00",
                    "review_status": "innovator_submitted_unverified",
                    "generation_number": 1, "profile": profile}
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (folder / "r.json").write_text(json.dumps(manifest), encoding="utf-8")
        (folder / "r.docx").write_bytes(make_docx_bytes(manifest))
        return str(folder / "r.json"), str(folder / "r.docx")

    def run_verify(self, paths):
        with redirect_stdout(io.StringIO()) as out:
            code = verify_downloads.main(*paths)
        return code, out.getvalue()

    def test_correct_submission_passes_every_check(self):
        code, out = self.run_verify(self.submission(edited=True))
        self.assertEqual(code, 0, out)
        self.assertNotIn("FAIL", out)

    def test_missing_innovator_edit_is_reported(self):
        code, out = self.run_verify(self.submission(edited=False))
        self.assertEqual(code, 1)
        self.assertIn("FAIL  innovator edit", out)


if __name__ == "__main__":
    unittest.main()
