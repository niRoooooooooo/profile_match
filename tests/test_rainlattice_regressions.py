"""Regression tests for issues found in the live RainLattice R3 report.

1. PDF table cells that wrap across lines were interleaved with neighbouring
   columns, so genuine quotes could not be verified (6 UNVERIFIED items).
2. Rows of a coded component table (RL-10 Housing, RL-11/12 outlets) were
   omitted from technology.components.
Offline only: PDFs are generated in memory; no network, no Gemini.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import pymupdf

import _fixtures as fx  # (also puts the backend on sys.path)
import _rainlattice_fixture as rl
from test_option_b import fact, rain_response, run, targets

from app.agents import profiling_agent as agent
from app.schemas.profile import Claim, InventionAIProfile
from app.services.document_parser import (
    TABLE_ROWS_HEADING, DocumentChunk, parse_document, reconstruct_table_rows)

REAL_DOCS = Path.home() / "Downloads" / "RainLattice_3_Test_Documents"


def pdf_with(lines, fontsize=10):
    """Build a one-page PDF; lines = [(x, y, text, fontsize?)]."""
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    for item in lines:
        x, y, text = item[:3]
        page.insert_text((x, y), text, fontsize=item[3] if len(item) > 3 else fontsize)
    data = document.tobytes()
    document.close()
    return data


WRAPPED_TABLE = [
    (60, 100, "Workstream"), (200, 100, "Proposed next test"), (420, 100, "Success evidence"),
    (60, 116, "Outdoor validation"), (200, 116, "Three roof materials, >= 20 real"),
    (420, 116, "Event records, failure"),
    (200, 129, "rainfall events across two seasons"), (420, 129, "logs"),
    (60, 145, "Maintenance"), (200, 145, "3-, 4- and 6-month wear/fouling"), (420, 145, "Measured clogging"),
    (200, 158, "comparison"),
]


class TableReconstructionTests(unittest.TestCase):
    def test_wrapped_cells_joined_and_quote_verifies(self):
        parsed = parse_document(pdf_with(WRAPPED_TABLE), "plan.pdf")
        text = parsed.chunks[0].text
        self.assertIn(TABLE_ROWS_HEADING, text)
        rows = text.split(TABLE_ROWS_HEADING)[1].strip().splitlines()
        self.assertIn("Outdoor validation | Three roof materials, >= 20 real rainfall events across "
                      "two seasons | Event records, failure logs", rows)
        self.assertIn("Maintenance | 3-, 4- and 6-month wear/fouling comparison | Measured clogging", rows)
        quote = "Three roof materials, >= 20 real rainfall events across two seasons"
        line_by_line = text.split(TABLE_ROWS_HEADING)[0]
        self.assertFalse(agent.excerpt_in_text(quote, line_by_line))     # the original failure
        self.assertTrue(agent.excerpt_in_text(quote, text))              # fixed

    def test_pages_without_wrapped_tables_are_unchanged(self):
        prose = [(60, 100, "A plain paragraph of text."), (60, 114, "Another line of prose.")]
        simple_table = [(60, 100, "Metric"), (250, 100, "Result"), (60, 114, "Flux"), (250, 114, "14 L/m2/h")]
        for lines in (prose, simple_table):
            text = parse_document(pdf_with(lines), "p.pdf").chunks[0].text
            self.assertNotIn(TABLE_ROWS_HEADING, text)

    def test_bullets_and_page_footers_are_not_table_cells(self):
        lines = [(60, 100, "Version"), (200, 100, "Date"), (330, 100, "Changes"),
                 (60, 114, "R3.0"), (200, 114, "14 October 2026"), (330, 114, "Changed screen to"),
                 (330, 127, "250 um after bench studies."),
                 (330, 140, "RainLattice R3 | synthetic material - Page 4"),
                 (60, 170, "•"), (80, 170, "The mock roof does not represent"),
                 (80, 183, "natural rainfall.")]
        text = parse_document(pdf_with(lines), "p.pdf").chunks[0].text
        rows = text.split(TABLE_ROWS_HEADING)[1].strip().splitlines()
        self.assertIn("R3.0 | 14 October 2026 | Changed screen to 250 um after bench studies.", rows)
        self.assertFalse(any("Page 4" in r for r in rows))
        self.assertFalse(any("mock roof" in r for r in rows))

    def test_reconstruction_never_raises(self):
        class Broken:
            def get_text(self, *args, **kwargs):
                raise RuntimeError("layout engine failure")
        self.assertEqual(reconstruct_table_rows(Broken()), [])


class QuoteNormalisationTests(unittest.TestCase):
    def test_symbol_variants_match_both_ways(self):
        self.assertTrue(agent.excerpt_in_text("at least ≥ 20 events", "at least >= 20 events"))
        self.assertTrue(agent.excerpt_in_text("<= 12 NTU threshold", "≤ 12 NTU threshold"))
        self.assertTrue(agent.excerpt_in_text("50 m² × 0.50 L/m²", "50 m2 x 0.50 L/m2"))

    def test_paraphrase_still_not_verified(self):
        source = "The control PCB samples turbidity, conductivity, temperature and flow pulses."
        self.assertFalse(agent.excerpt_in_text("flow measurement", source))
        self.assertFalse(agent.excerpt_in_text("conductivity sensing", source))


class UnverifiedHandlingTests(unittest.TestCase):
    def test_paraphrased_technique_stays_unverified_and_keeps_its_quote(self):
        payload = rain_response(extra=[fact("technology.techniques", "conductivity sensing", rl.SPEC,
                                            "conductivity sensing", page=2)])
        result, _ = run("rain", [payload])
        claim = next(c for c in result.profile.technology.techniques if c.value == "conductivity sensing")
        self.assertEqual((claim.classification, claim.evidence), ("inference", []))
        self.assertTrue(claim.explanation.startswith("UNVERIFIED"))
        self.assertIn("Unlocated quote: “conductivity sensing”", claim.explanation)

    def test_flagging_twice_does_not_repeat_the_quote(self):
        claim = Claim(value="x", classification="document_fact",
                      evidence=[{"source_file": "a.pdf", "page": 1, "excerpt": "quoted text"}])
        agent._flag_unverified(claim)
        agent._flag_unverified(claim)
        self.assertEqual(claim.explanation.count("Unlocated quote"), 1)


SPEC_TABLE = ("Code | Subsystem | R3 technical specification | Role\n"
              "RL-01 | Intake screen | 250 µm stainless-steel mesh | Captures coarse fragments\n"
              "RL-07 | Controller | ESP32-S3 with watchdog | Local state logic\n"
              "RL-10 | Housing | IP54 target enclosure; no IP rating certified | Serviceable case\n"
              "RL-11 | Collection outlet | 25 mm nominal PVC-compatible connector | Tank connection\n"
              "RL-12 | Divert outlet | 25 mm nominal drain connector | Directs initial runoff")


class ComponentCoverageTests(unittest.TestCase):
    def index(self):
        return {rl.SPEC: [DocumentChunk(source_file=rl.SPEC, page=2, text=SPEC_TABLE)]}

    def test_coded_component_rows_found(self):
        self.assertEqual(agent.table_component_names(self.index()),
                         ["Intake screen", "Controller", "Housing", "Collection outlet", "Divert outlet"])
        plain = {"x.pdf": [DocumentChunk(source_file="x.pdf", page=1,
                                         text="RL-01      Intake screen      250 um mesh\n"
                                              "RL-02      Flow sensor      paddle\n"
                                              "RL-03      Housing      IP54\nSubsystem list")]}
        self.assertEqual(agent.table_component_names(plain), ["Intake screen", "Flow sensor", "Housing"])
        self.assertEqual(agent.table_component_names(
            {"y.pdf": [DocumentChunk(source_file="y.pdf", page=1, text="RL-01 | A | b\nRL-02 | C | d")]}), [])

    def test_missing_rows_reported(self):
        profile = InventionAIProfile()
        profile.technology.components = [Claim(value="controller", classification="inference"),
                                         Claim(value="250 µm intake screen", classification="inference")]
        self.assertEqual(agent.missing_table_components(profile, self.index()),
                         ["Housing", "Collection outlet", "Divert outlet"])

    def test_repair_adds_omitted_components_without_dropping_existing_ones(self):
        processed = rl.rain_processed_result()
        processed.documents[0].parsed.chunks.append(DocumentChunk(source_file=rl.SPEC, page=2, text=SPEC_TABLE))
        payload = json.loads(rain_response())
        before = [c["value"] for c in payload["claims"] if c["field"] == "technology.components"]
        quote = lambda name, excerpt: {"value": name, "classification": "document_fact",  # noqa: E731
                                       "evidence": [{"source_file": rl.SPEC, "page": 2, "excerpt": excerpt}]}
        repair = {"components": [quote("Housing", "Housing | IP54 target enclosure"),
                                 quote("Collection outlet", "Collection outlet | 25 mm nominal"),
                                 quote("Divert outlet", "Divert outlet | 25 mm nominal drain connector"),
                                 {"value": "Waterproof antenna", "classification": "document_fact",
                                  "evidence": [{"source_file": rl.SPEC, "page": 2, "excerpt": "antenna"}]}]}
        result, client = run("rain", [json.dumps(payload), json.dumps(repair)], processed=processed)
        self.assertIn("components", targets(client))
        self.assertIn("component_table_rows_not_yet_listed", client.calls[1][1])
        values = [c.value for c in result.profile.technology.components]
        self.assertEqual(values[:len(before)], before)                        # nothing dropped
        for name in ("Housing", "Collection outlet", "Divert outlet"):
            self.assertIn(name, values)
        self.assertNotIn("Waterproof antenna", values)                        # unquoted: rejected

    def test_complete_component_list_needs_no_extra_request(self):
        result, client = run("rain", [rain_response()])      # fixture has no coded component table
        self.assertEqual(len(client.calls), 1)


class PromptTests(unittest.TestCase):
    def test_prompt_covers_tables_components_and_calibration(self):
        text = " ".join(agent.GEMINI_EXTRACTION_INSTRUCTIONS.split())
        for rule in ("include EVERY row", "housings/enclosures, inlets, outlets",
                     "calibration and accuracy checks", "paraphrased technique name is an inference",
                     "[Table rows from this page, with wrapped cells joined]", "quote the text of ONE cell"):
            self.assertIn(rule, text)


class VerifyDownloadsRainLatticeTests(unittest.TestCase):
    def test_rainlattice_mode_and_previous_snapshot(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent / "e2e_live"))
        import verify_downloads
        from app.services.profile_submission_service import make_docx_bytes

        result, _ = run("rain", [rain_response()])
        profile = result.profile.model_dump(mode="json")
        profile["commercialization"]["product_concept"] = {
            "value": "Integrated diverter unit (E2E innovator edit)", "classification": "inference",
            "evidence": [], "explanation": "Innovator-edited statement; not independently verified "
                                           "against source documents."}
        manifest = {"schema_version": 1, "submission_id": "20261125T120000Z-abcdef123456",
                    "invention_id": rl.RAIN_INVENTION_ID, "submitted_by": fx.OWNER_ID,
                    "submitted_at": "2026-11-25T12:00:00+00:00",
                    "review_status": "innovator_submitted_unverified", "generation_number": 1,
                    "profile": profile}
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "r.json").write_text(json.dumps(manifest), encoding="utf-8")
            (folder / "r.docx").write_bytes(make_docx_bytes(manifest))
            (folder / "old.json").write_text("snapshot A", encoding="utf-8")
            (folder / "old-again.json").write_text("snapshot A", encoding="utf-8")
            (folder / "changed.json").write_text("snapshot B", encoding="utf-8")
            with redirect_stdout(io.StringIO()) as out:
                code = verify_downloads.main(str(folder / "r.json"), str(folder / "r.docx"), "rainlattice",
                                             (str(folder / "old.json"), str(folder / "old-again.json")))
            self.assertEqual(code, 0, out.getvalue())
            for line in ("PASS  TRL 5 (registration) vs TRL 4 (documents) discrepancy kept",
                         "PASS  4 vs 6 month maintenance contradiction kept with both sources",
                         "PASS  DOCX has the 15 numbered report sections",
                         "PASS  every DOCX citation link points to a reference",
                         "PASS  earlier submitted snapshot is unchanged"):
                self.assertIn(line, out.getvalue())
            with redirect_stdout(io.StringIO()) as out:
                code = verify_downloads.main(str(folder / "r.json"), str(folder / "r.docx"), "rainlattice",
                                             (str(folder / "old.json"), str(folder / "changed.json")))
            self.assertEqual(code, 1)
            self.assertIn("FAIL  earlier submitted snapshot is unchanged", out.getvalue())


@unittest.skipUnless((REAL_DOCS / "RainLattice_R3_Technical_Specification.pdf").exists(),
                     "fictional RainLattice documents not present on this machine")
class RealRainLatticeDocumentTests(unittest.TestCase):
    """The original failing passages, on the real fictional RainLattice PDFs."""

    def test_previously_unverified_table_passages_now_verify(self):
        name = "RainLattice_R3_Prototype_Testing_and_Validation.pdf"
        page5 = next(c for c in parse_document((REAL_DOCS / name).read_bytes(), name).chunks if c.page == 5)
        for quote in ("Three roof materials, >= 20 real rainfall events across at least two seasons",
                      "Tested hysteresis/state transition, measured response",
                      "3-, 4- and 6-month wear/fouling comparison",
                      "Independent laboratory sampling per target region"):
            self.assertTrue(agent.excerpt_in_text(quote, page5.text), quote)

    def test_all_twelve_subsystems_visible(self):
        name = "RainLattice_R3_Technical_Specification.pdf"
        parsed = parse_document((REAL_DOCS / name).read_bytes(), name)
        names = agent.table_component_names({name: parsed.chunks})
        self.assertEqual(len(names), 12)
        for expected in ("Housing", "Collection outlet", "Divert outlet"):
            self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main()
