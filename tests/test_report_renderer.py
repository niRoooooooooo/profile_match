"""Offline tests: one unified report (web + DOCX) from FICTIONAL data."""

import copy
import io
import json
import os
import re
import unittest
from unittest import mock

import _fixtures as fx
import _large_fixture as lf
from docx import Document
from test_large_fixture import FakeGemini as LargeFake, simulated_response

from app.agents import profiling_agent as agent
from app.api.profiles import report_for
from app.schemas.profile import InventionAIProfile
from app.services.report_docx import build_submission_docx
from app.services.report_renderer import NOT_DOCUMENTED, REPORT_NOTICE, render_report, render_report_json

CLEAN = {k: v for k, v in os.environ.items()
         if not k.startswith(("GEMINI_", "PROFILING_", "CLOUD_PROCESSING_"))}
TITLES = [
    "Executive Summary", "Invention Overview", "Problem Statement and Objectives",
    "Proposed Solution and Working Principle", "Technology Description and Core Components",
    "Novelty and Technical Advantages", "Prototype Development and Technology Readiness",
    "Testing Methods and Experimental Results", "Applications and Relevant Industries",
    "Intellectual Property and Ownership", "Commercialization Potential and Requirements",
    "Required Industry Partner Capabilities", "Technical Limitations and Risks",
    "Research Gaps, Missing Information and Recommended Next Steps",
    "Source Documents and References"]


class GlowfernGemini:
    provider, model = "gemini", "gemini-3.5-flash-lite"

    def remaining_requests_today(self):
        return 9

    def generate_structured(self, prompt, response_model, **kwargs):
        return response_model.model_validate_json(fx.comprehensive_json())


def glowfern_profile():
    with mock.patch.dict(os.environ, {**CLEAN, "GEMINI_APPROVED_INVENTION_IDS": fx.INVENTION_ID},
                         clear=True):
        return agent.build_profile_from_processed(
            fx.processed_result(), ai_client=GlowfernGemini(), cloud_processing_consent=True).profile


def tidewell_profile():
    with mock.patch.dict(os.environ, {**CLEAN, "GEMINI_APPROVED_INVENTION_IDS": lf.LARGE_INVENTION_ID},
                         clear=True):
        return agent.build_profile_from_processed(
            lf.large_processed_result(), ai_client=LargeFake([json.dumps(simulated_response())]),
            cloud_processing_consent=True).profile


def pre_option_b(data):
    """A saved draft from before Option B: no mechanism, methods or justification."""
    data["problem_solution"]["working_mechanism"] = None
    data["problem_solution"]["solution"] = None
    data["development"]["testing_methods"] = []
    data["readiness"]["justification"] = None
    return data


def section(report, number):
    return report.sections[number - 1]


def section_text(sec):
    parts = []
    for block in sec.blocks:
        parts += [block.heading or "", block.text or ""]
        parts += [f"{i.name or ''} {i.text}" for i in block.items]
    return " ".join(parts)


def items(report):
    return [i for s in report.sections for b in s.blocks for i in b.items]


class StructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.glowfern = render_report(glowfern_profile(), {"generation_number": 1})
        cls.tidewell = render_report(tidewell_profile(), {"generation_number": 2})

    def test_one_report_with_fifteen_numbered_sections(self):
        for report in (self.glowfern, self.tidewell):
            self.assertEqual([s.title for s in report.sections], TITLES)
            self.assertEqual([s.number for s in report.sections], list(range(1, 16)))
            self.assertEqual(report.notice, REPORT_NOTICE)

    def test_every_section_has_content_or_a_single_missing_note(self):
        for report in (self.glowfern, self.tidewell):
            for sec in report.sections:
                self.assertTrue(sec.blocks, sec.title)
                for block in sec.blocks:
                    self.assertTrue(block.items or block.text, (sec.title, block.kind))
                notes = [b for b in sec.blocks if b.kind == "note" and b.text == NOT_DOCUMENTED]
                if notes:
                    self.assertEqual(len(sec.blocks), 1, sec.title)  # only the note, no empty boxes

    def test_all_relevant_documents_contribute_and_unrelated_excluded(self):
        cited = {s.source_file for s in self.tidewell.sources}
        self.assertEqual(cited, {lf.TECH, lf.TESTS, lf.MEMO})
        sources = section_text(section(self.tidewell, 15))
        self.assertIn(f"{lf.UNRELATED} (unrelated)", sources)
        self.assertNotIn(lf.UNRELATED, cited)
        self.assertNotIn("Staff parking", " ".join(i.text for i in items(self.tidewell)))

    def test_citations_are_numbered_once_and_resolve(self):
        for report in (self.glowfern, self.tidewell):
            numbers = [s.number for s in report.sources]
            self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
            keys = [(s.source_file, s.page, s.section) for s in report.sources]
            self.assertEqual(len(keys), len(set(keys)))
            for item in items(report):
                for n in item.citations:
                    self.assertIn(n, numbers)
                if item.status == "verified":
                    self.assertTrue(item.citations, item.text)

    def test_components_clear_without_repeated_source_text(self):
        comp = next(b for b in section(self.tidewell, 5).blocks if b.kind == "bullets")
        texts = [i.text for i in comp.items]
        self.assertEqual(len(texts), 6)
        self.assertTrue(all(len(t) < 40 for t in texts), texts)  # names, not quoted sentences
        # Excerpts live only in the Sources section, not in the item text.
        self.assertFalse(any("stack with a titanium" in t for t in texts))

    def test_results_keep_figures_and_units_in_a_table(self):
        table = next(b for b in section(self.tidewell, 8).blocks if b.kind == "table")
        text = " ".join(i.text for i in table.items)
        for figure in ("97.2 %", "14 L/m2/h", "1.8 kWh/m3", "500 hours"):
            self.assertIn(figure, text)
        self.assertNotIn("91%", text)  # superseded prototype-v1 value

    def test_novelty_qualifier_and_assessment_note_preserved(self):
        text = section_text(section(self.tidewell, 6))
        self.assertIn("(authors' claim)", text)
        self.assertIn("have not been independently assessed", text)

    def test_applications_industries_customers_separated(self):
        headings = [b.heading for b in section(self.tidewell, 9).blocks if b.kind == "bullets"]
        self.assertEqual(headings[:2], ["Use cases", "Industries"])
        uses = section(self.tidewell, 9).blocks[0]
        self.assertEqual([i.text for i in uses.items],
                         ["Coastal villages", "Disaster-relief shelters", "Small island resorts"])

    def test_trl_declared_vs_estimated_and_discrepancy_reported(self):
        prototype = section_text(section(self.tidewell, 7))
        self.assertIn("Declared TRL TRL 5", prototype)
        self.assertIn("TRL 4 (indicative estimate; not a certification)", prototype)
        risks = section(self.tidewell, 13)
        disc = [i for b in risks.blocks for i in b.items if i.status == "discrepancy"]
        self.assertEqual(len(disc), 1)
        self.assertIn("registration states “5”", disc[0].text)
        self.assertTrue(disc[0].citations)

    def test_source_locations_accurate(self):
        prototype = next(i for i in items(self.tidewell) if i.path == "development.prototype_status")
        source = self.tidewell.sources[prototype.citations[0] - 1]
        self.assertEqual((source.source_file, source.page), (lf.TECH, 4))  # corrected page

    def test_missing_information_acknowledged_without_claiming_absence(self):
        gaps = section_text(section(self.glowfern, 14))
        for expected in ("Information not documented in the uploaded materials",
                         "Supply chain (Section 11)", "may still exist"):
            self.assertIn(expected, gaps)
        self.assertEqual(section(self.glowfern, 11).blocks[0].text, NOT_DOCUMENTED)
        all_text = " ".join(section_text(s) for s in self.glowfern.sections).lower()
        for forbidden in ("does not exist", "no patent exists", "there is no supply chain"):
            self.assertNotIn(forbidden, all_text)

    def test_labels_distinguish_evidence_types(self):
        statuses = {i.status for i in items(self.glowfern)}
        self.assertTrue({"verified", "interpretation", "declared", "unverified",
                         "recommendation"} <= statuses)
        lumens = next(i for i in items(self.glowfern) if "300 lumens" in i.text)
        self.assertEqual((lumens.status, lumens.label, lumens.citations), ("unverified", "Unverified", []))
        partner = next(i for i in items(self.glowfern) if i.text == "Field-testing laboratory")
        self.assertEqual(partner.status, "recommendation")
        block = next(b for b in section(self.glowfern, 12).blocks if partner in b.items)
        self.assertEqual((block.label, partner.label), ("AI recommendations", None))  # once per block

    def test_no_duplicate_facts_within_a_section(self):
        for report in (self.glowfern, self.tidewell):
            for sec in report.sections[:-1]:
                texts = [i.text.casefold() for b in sec.blocks for i in b.items if b.kind != "note"]
                self.assertEqual(len(texts), len(set(texts)), sec.title)


class MissingInformationTests(unittest.TestCase):
    """Partly documented vs missing; no repeated or stale entries."""

    @classmethod
    def setUpClass(cls):
        cls.data = pre_option_b(glowfern_profile().model_dump(mode="json"))

    def lists(self, data):
        gaps = section(render_report(data), 14)
        return {b.heading: [i.text for i in b.items] for b in gaps.blocks if b.kind == "bullets"}

    def test_partial_coverage_points_to_related_sections(self):
        report = render_report(self.data)
        notes = " ".join(b.text for b in section(report, 4).blocks if b.kind == "note")
        self.assertIn("Working principle: no separate description was extracted", notes)
        self.assertIn("core components (Section 5)", notes)
        testing = " ".join(b.text for b in section(report, 8).blocks if b.kind == "note")
        # the only result is UNVERIFIED, so it is not "documented" evidence (R2)
        self.assertIn("prototype status (Section 7)", testing)
        self.assertNotIn("experimental results", testing)
        self.assertNotIn("Testing methods: not documented", testing)
        lists = self.lists(self.data)
        self.assertIn("Working principle (Section 4) — related information: core components (Section 5)",
                      lists["Partly documented"])
        missing = lists["Information not documented in the uploaded materials"]
        self.assertFalse(any(m.startswith(("Working principle", "Testing methods")) for m in missing))
        # nothing invented: the saved field stays empty
        self.assertFalse((self.data["problem_solution"]["working_mechanism"] or {}).get("value"))

    def test_truly_missing_when_no_related_evidence(self):
        data = copy.deepcopy(self.data)
        data["development"]["experimental_results"] = []
        data["development"]["prototype_status"] = {"value": None, "classification": "missing",
                                                   "evidence": [], "explanation": None}
        missing = self.lists(data)["Information not documented in the uploaded materials"]
        self.assertIn("Testing methods (Section 8)", missing)

    def test_ai_notes_merged_with_section_gaps_once(self):
        data = copy.deepcopy(self.data)
        data["missing_information"] = ["No cost data.", "Supply chain information not documented",
                                       "Manufacturing process details are not provided"]
        missing = self.lists(data)["Information not documented in the uploaded materials"]
        self.assertIn("No cost data (Section 11)", missing)
        self.assertNotIn("Documented costs (Section 11)", missing)
        self.assertEqual(sum("upply" in m for m in missing), 1)
        self.assertEqual(sum("anufactur" in m for m in missing), 1)
        self.assertIn("Manufacturing process details are not provided (Section 11)", missing)

    def test_stale_notes_for_documented_fields_hidden(self):
        data = copy.deepcopy(self.data)
        data["missing_information"] = ["Specific industries not identified", "Use cases not documented",
                                       "No independent validation of brightness results"]
        missing = self.lists(data)["Information not documented in the uploaded materials"]
        self.assertFalse(any("industries" in m.lower() or "use cases" in m.lower() for m in missing))
        self.assertIn("No independent validation of brightness results (Section 8)", missing)  # kept
        self.assertEqual(data["missing_information"][0], "Specific industries not identified")

    def test_duplicate_list_items_are_not_reported_missing(self):
        data = copy.deepcopy(self.data)
        data["applications"]["industries"] = copy.deepcopy(data["applications"]["use_cases"])
        notes = " ".join(b.text or "" for b in section(render_report(data), 9).blocks)
        self.assertNotIn("Industries", notes)

    def test_only_cited_document_facts_count_as_related_evidence(self):
        data = copy.deepcopy(self.data)
        data["problem_solution"]["solution"] = {"value": "A sealed moss marker.", "classification": "inference",
                                                "evidence": [], "explanation": "AI synthesis."}
        data["technology"]["components"] = []
        notes = " ".join(b.text for b in section(render_report(data), 4).blocks if b.kind == "note")
        self.assertNotIn("proposed solution (this section)", notes)       # uncited interpretation
        self.assertIn("Working principle: not documented", notes)

    def test_cited_interpretation_never_looks_like_a_verified_fact(self):
        data = copy.deepcopy(self.data)
        fact = copy.deepcopy(data["technology"]["components"][1])
        data["applications"]["industries"] = [
            {"value": "Outdoor lighting", "classification": "document_fact",
             "evidence": fact["evidence"], "explanation": None},
            {"value": "Biotechnology", "classification": "inference",
             "evidence": fact["evidence"], "explanation": "Inferred from the moss."}]
        block = next(b for b in section(render_report(data), 9).blocks if b.heading == "Industries")
        self.assertIsNone(block.label)                                     # no "unless cited"
        inferred = next(i for i in block.items if i.text == "Biotechnology")
        self.assertEqual(inferred.label, "AI interpretation")

    def test_notes_get_section_numbers_and_case_insensitive_dedupe(self):
        data = copy.deepcopy(self.data)
        data["missing_information"] = ["Target customer categories", "Specific maintenance requirements",
                                       "Supply chain", "supply chain"]
        missing = self.lists(data)["Information not documented in the uploaded materials"]
        self.assertIn("Target customer categories (Section 9)", missing)
        self.assertIn("Specific maintenance requirements (Section 11)", missing)
        self.assertEqual(sum(m.lower().startswith("supply chain") for m in missing), 1)

    def test_trl_matching_note(self):
        data = copy.deepcopy(self.data)
        data["readiness"]["reported_trl"] = data["readiness"]["suggested_trl"] = 3
        trl = next(i for i in items(render_report(data)) if i.path == "readiness.suggested_trl")
        self.assertEqual(trl.text, "TRL 3 (matches the declared TRL)")
        data["readiness"]["suggested_trl"] = 4
        trl = next(i for i in items(render_report(data)) if i.path == "readiness.suggested_trl")
        self.assertIn("indicative estimate", trl.text)

    def test_reference_without_excerpt_gets_note(self):
        data = copy.deepcopy(self.data)
        data["technology"]["components"][0]["evidence"].append(
            {"source_file": fx.RELEVANT, "page": 9, "excerpt": "“ ”"})
        entry = next(e for e in render_report(data).sources if e.page == 9)
        self.assertEqual((entry.excerpts, entry.note), ([], "No excerpt was recorded for this citation."))


class CompatibilityTests(unittest.TestCase):
    def test_deterministic_and_input_not_mutated(self):
        data = glowfern_profile().model_dump(mode="json")
        before = json.dumps(data, sort_keys=True)
        first, second = render_report_json(data), render_report_json(data)
        self.assertEqual(first, second)
        self.assertEqual(json.dumps(data, sort_keys=True), before)
        json.loads(json.dumps(first))  # JSON-serialisable for the API

    def test_empty_and_legacy_profiles_render(self):
        empty = render_report(InventionAIProfile())
        self.assertEqual(len(empty.sections), 15)
        self.assertEqual(empty.title, "Untitled invention")
        legacy = glowfern_profile().model_dump(mode="json")
        legacy["discrepancies"] = [{"field": "trl", "registration_value": "3",
                                    "document_value": "TRL 4", "evidence": []}]  # no "kind"
        report = render_report(legacy)
        self.assertIn("registration states", section_text(section(report, 13)))

    def test_between_document_contradiction_rendered_unresolved(self):
        data = glowfern_profile().model_dump(mode="json")
        data["discrepancies"] = [{
            "field": "development.prototype_status", "kind": "between_documents",
            "document_value": "Prototype v2", "other_document_value": "Prototype v3",
            "evidence": [{"source_file": fx.RELEVANT, "page": 2, "excerpt": "A laboratory prototype"},
                         {"source_file": fx.RELEVANT, "page": 1, "excerpt": "sealed acrylic housing"}]}]
        item = [i for b in section(render_report(data), 13).blocks for i in b.items][-1]
        self.assertEqual(item.label, "Unresolved contradiction")
        self.assertIn("“Prototype v2” versus “Prototype v3”", item.text)
        self.assertIn("Not resolved", item.text)
        self.assertEqual(len(item.citations), 2)

    def test_innovator_edit_shown_as_edited_without_citation(self):
        data = glowfern_profile().model_dump(mode="json")
        data["development"]["prototype_status"] = {
            "value": "Prototype v2 (innovator wording)", "classification": "inference",
            "evidence": [], "explanation": "Innovator-edited statement; not independently "
                                           "verified against source documents."}
        item = next(i for i in items(render_report(data)) if i.path == "development.prototype_status")
        self.assertEqual((item.status, item.label, item.citations), ("edited", "Innovator-edited", []))

    def test_api_report_field_and_safe_failure(self):
        draft = {"edited_data": glowfern_profile().model_dump(mode="json"),
                 "generation_number": 3, "updated_at": "2026-11-24T12:00:00+00:00"}
        report = report_for(draft)
        self.assertEqual(len(report["sections"]), 15)
        self.assertIn({"name": "AI generation", "value": "3"}, report["processing"])
        self.assertEqual(report["version"], "Current editable draft — last saved 24 Nov 2026, 12:00 UTC")
        self.assertIsNone(report_for(None))
        with self.assertLogs("app.api.profiles", level="WARNING"):
            self.assertIsNone(report_for({"edited_data": {"identity": "not valid"}}))


class DocxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = {"invention_id": lf.LARGE_INVENTION_ID, "submission_id": "20261124T120000Z-abcdef123456",
                    "submitted_at": "2026-11-24T12:00:00+00:00", "generation_number": 2,
                    "review_status": "innovator_submitted_unverified",
                    "profile": tidewell_profile().model_dump(mode="json")}
        cls.manifest = manifest
        cls.document = Document(io.BytesIO(build_submission_docx(manifest)))
        cls.paragraphs = [(p.style.name, p.text) for p in cls.document.paragraphs]
        cls.text = "\n".join(t for _, t in cls.paragraphs)

    def test_title_banner_metadata_and_footer(self):
        self.assertEqual(self.paragraphs[0], ("Title", "Tidewell Solar Desalination Cartridge"))
        self.assertIn(REPORT_NOTICE, self.text)
        meta = {row.cells[0].text: row.cells[1].text for row in self.document.tables[0].rows}
        self.assertEqual(set(meta), {"Technical domain", "Declared TRL", "Version",
                                     "Submission ID", "Review status"})   # short header
        self.assertEqual(meta["Submission ID"], "20261124T120000Z-abcdef123456")
        self.assertTrue(meta["Version"].startswith("Submitted snapshot of 24 Nov 2026, 12:00 UTC"))
        self.assertIn("pending future institutional review", meta["Review status"])
        record = {row.cells[0].text: row.cells[1].text for row in self.document.tables[-1].rows}
        self.assertEqual(record["AI generation"], "2")                     # appendix only
        self.assertIn("AI model", record)
        self.assertNotIn("AI model", meta)
        footer = self.document.sections[0].footer.paragraphs[0].text
        self.assertIn("Not institutionally approved", footer)

    def test_numbered_sections_as_real_headings(self):
        headings = [t for style, t in self.paragraphs if style == "Heading 1"]
        self.assertEqual(headings[:15], [f"{n}. {t}" for n, t in enumerate(TITLES, 1)])

    def test_results_table_with_figures(self):
        table = self.document.tables[1]
        # all results are documented facts: no repetitive Status column
        self.assertEqual([c.text for c in table.rows[0].cells], ["Result", "Source"])
        body = " ".join(c.text for row in table.rows[1:] for c in row.cells)
        for figure in ("97.2 %", "14 L/m2/h", "1.8 kWh/m3"):
            self.assertIn(figure, body)
        self.assertRegex(body, r"\[\d+\]")

    def test_paragraphs_bullets_labels_and_references(self):
        styles = {s for s, _ in self.paragraphs}
        self.assertIn("List Bullet", styles)
        self.assertIn("(AI interpretation)", self.text)
        self.assertIn("(AI recommendations)", self.text)
        self.assertLessEqual(self.text.count("(AI interpretation)"), 15)  # not per item
        self.assertIn("References", self.text)
        self.assertRegex(self.text, rf"\[\d+\] {re.escape(lf.TESTS)} \(page 1\)")
        self.assertNotIn("Item 1", self.text)
        self.assertNotIn("Status: ", self.text)  # old form-style labels gone

    def test_citations_are_internal_links_without_urls(self):
        import zipfile
        raw = build_submission_docx(self.manifest)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            body = archive.read("word/document.xml").decode("utf-8")
            rels = archive.read("word/_rels/document.xml.rels").decode("utf-8")
        anchors = set(re.findall(r'w:anchor="(ref_\d+)"', body))
        bookmarks = set(re.findall(r'w:bookmarkStart[^>]*w:name="(ref_\d+)"', body))
        self.assertTrue(anchors)
        self.assertLessEqual(anchors, bookmarks)                     # every link has a target
        text = re.sub(r'xmlns(:\w+)?="[^"]*"', '', body)            # XML namespaces are not links
        for forbidden in ("localhost", "127.0.0.1", "http://", "https://"):
            self.assertNotIn(forbidden, text)
        self.assertNotRegex(body, r'<w:hyperlink [^>]*r:id=')            # no external hyperlinks
        self.assertNotIn('TargetMode="External"', rels)

    def test_no_crowded_technical_metadata_before_section_1(self):
        header = self.text.split("1. Executive Summary")[0].lower()
        header += " ".join(c.text for row in self.document.tables[0].rows for c in row.cells).lower()
        for technical in ("gemini", "allowlist", "demo mode", "consent", lf.LARGE_INVENTION_ID):
            self.assertNotIn(technical, header)

    def test_references_show_complete_quotations(self):
        sources = render_report(self.manifest["profile"]).sources
        self.assertTrue(any(len(s.excerpts) > 3 for s in sources) or sources)
        for source in sources:
            for excerpt in source.excerpts:
                self.assertIn(f"“{excerpt}”", self.text)                   # all, never truncated

    def test_docx_reflects_latest_edits(self):
        edited = copy.deepcopy(self.manifest)
        edited["profile"]["technology"]["components"][0] = {
            "value": "Graphene-oxide membrane (EDITED)", "classification": "inference",
            "evidence": [], "explanation": "Innovator-edited statement; not independently "
                                           "verified against source documents."}
        text = "\n".join(p.text for p in Document(io.BytesIO(build_submission_docx(edited))).paragraphs)
        self.assertIn("Graphene-oxide membrane (EDITED) (Innovator-edited)", text)
        self.assertNotIn("graphene-oxide membrane stack [", text)


if __name__ == "__main__":
    unittest.main()
