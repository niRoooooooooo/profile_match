"""Offline Profiling Agent tests with FICTIONAL data. No live AI calls."""

import asyncio
import importlib.util
import json
import os
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _fixtures as fx

from app.agents import profiling_agent as agent
from app.schemas.profile import Claim, Evidence, InventionAIProfile
from app.services import cloud_authorization as auth
from app.services.cloud_authorization import CloudProcessingNotAuthorized
from app.services.gemini_client import (
    FreeTierRateLimiter,
    GeminiClient,
    GeminiQuotaError,
)

ROOT = Path(__file__).resolve().parents[1]
CLEAN_ENV = {
    k: v for k, v in os.environ.items()
    if not k.startswith(("GEMINI_", "PROFILING_", "CLOUD_PROCESSING_"))
}
APPROVED = {"GEMINI_APPROVED_INVENTION_IDS": fx.INVENTION_ID}


class FakeGemini:
    """Agent-level fake honouring the generate_structured interface."""

    provider = "gemini"
    model = "gemini-3.5-flash-lite"

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def remaining_requests_today(self):
        return 10

    def generate_structured(self, prompt, response_model, **kwargs):
        self.calls.append((response_model.__name__, prompt))
        item = self.payloads.pop(0)
        if isinstance(item, Exception):
            raise item
        return response_model.model_validate_json(item)


def index():
    return agent.build_verification_index(fx.processed_result(), {fx.RELEVANT})


# ---------------------------------------------------------------------------
# Deterministic citation verification
# ---------------------------------------------------------------------------

class ExcerptMatchingTests(unittest.TestCase):
    def test_typography_and_hyphenation_tolerated(self):
        self.assertTrue(agent.excerpt_in_text('A "low-power" photodiode', fx.PAGE_1))
        self.assertTrue(agent.excerpt_in_text("moisture-retaining gel pad", fx.PAGE_1))

    def test_ellipsis_segments_must_appear_in_order(self):
        self.assertTrue(agent.excerpt_in_text(
            "sealed acrylic housing ... reports brightness to an ESP32", fx.PAGE_1))
        self.assertFalse(agent.excerpt_in_text(
            "reports brightness to an ESP32 ... sealed acrylic housing", fx.PAGE_1))

    def test_paraphrase_rejected(self):
        self.assertFalse(agent.excerpt_in_text("an acrylic enclosure that is sealed", fx.PAGE_1))
        self.assertFalse(agent.excerpt_in_text("measured 300 lumens", fx.PAGE_2))

    def test_wrong_page_is_corrected_not_discarded(self):
        found, corrected = agent.locate_evidence(
            Evidence(source_file=fx.RELEVANT, page=2, excerpt="an ESP32 microcontroller"),
            index(),
        )
        self.assertTrue(corrected)
        self.assertEqual(found.page, 1)

    def test_strict_verify_still_location_sensitive(self):
        ev = Evidence(source_file=fx.RELEVANT, page=2, excerpt="an ESP32 microcontroller")
        self.assertFalse(agent.verify_evidence(ev, index()))


class ClaimValidationTests(unittest.TestCase):
    def profile_with(self, **development):
        profile = InventionAIProfile()
        for key, value in development.items():
            setattr(profile.development, key, value)
        return profile

    def test_unverified_document_fact_flagged_not_deleted(self):
        claim = Claim.model_validate(fx.fact("300 lumens", "measured 300 lumens", page=2))
        profile = self.profile_with(experimental_results=[claim])
        warnings = agent.validate_claim_evidence(
            profile, index(), fx.fictional_invention(), {fx.UNRELATED})
        result = profile.development.experimental_results[0]
        self.assertEqual(result.value, "300 lumens")
        self.assertEqual(result.classification, "inference")
        self.assertEqual(result.evidence, [])
        self.assertTrue(result.explanation.startswith("UNVERIFIED"))
        self.assertTrue(any("UNVERIFIED" in w for w in warnings))

    def test_claim_citing_only_excluded_document_removed(self):
        claim = Claim.model_validate(
            fx.fact("Requires feeding", "feeding schedule", source=fx.UNRELATED))
        profile = self.profile_with(technical_limitations=[claim])
        agent.validate_claim_evidence(profile, index(), fx.fictional_invention(), {fx.UNRELATED})
        result = profile.development.technical_limitations[0]
        self.assertEqual(result.classification, "missing")
        self.assertIsNone(result.value)

    def test_value_verbatim_rescues_bad_excerpt(self):
        claim = Claim.model_validate(
            fx.fact("No field validation has been performed", "invented text", page=2))
        profile = self.profile_with(technical_limitations=[claim])
        agent.validate_claim_evidence(profile, index(), fx.fictional_invention())
        result = profile.development.technical_limitations[0]
        self.assertEqual(result.classification, "document_fact")
        self.assertEqual(result.evidence[0].page, 2)

    def test_fabricated_evidence_removed_from_inference(self):
        claim = Claim(value="Likely durable", classification="inference",
                      evidence=[Evidence(source_file=fx.RELEVANT, excerpt="made up quote")])
        profile = self.profile_with(technical_limitations=[claim])
        agent.validate_claim_evidence(profile, index(), fx.fictional_invention())
        self.assertEqual(profile.development.technical_limitations[0].evidence, [])

    def test_registration_mismatch_flagged(self):
        profile = InventionAIProfile()
        profile.technology.primary_domain = Claim(
            value="Marine robotics", classification="registration_fact")
        agent.validate_claim_evidence(profile, index(), fx.fictional_invention())
        result = profile.technology.primary_domain
        self.assertEqual(result.classification, "inference")
        self.assertTrue(result.explanation.startswith("UNVERIFIED"))

    def test_prevalidator_downgrades_instead_of_failing(self):
        class Wrapper(agent.EvidenceAwareExtraction):
            claim: Claim

        token = agent._ACTIVE_SOURCE_INDEX.set(index())
        try:
            parsed = Wrapper.model_validate(
                {"claim": {"value": "Glows for a year", "classification": "document_fact"}})
        finally:
            agent._ACTIVE_SOURCE_INDEX.reset(token)
        self.assertEqual(parsed.claim.classification, "inference")
        self.assertTrue(parsed.claim.explanation.startswith("UNVERIFIED"))


# ---------------------------------------------------------------------------
# Cloud authorization: public is necessary but NOT sufficient
# ---------------------------------------------------------------------------

@mock.patch.dict(os.environ, CLEAN_ENV, clear=True)
class CloudAuthorizationTests(unittest.TestCase):
    def test_public_alone_is_not_enough(self):
        self.assertFalse(auth.is_cloud_processing_authorized(fx.fictional_invention("public")))

    def test_public_and_allowlisted_is_authorized(self):
        with mock.patch.dict(os.environ, APPROVED):
            self.assertTrue(auth.is_cloud_processing_authorized(fx.fictional_invention("public")))

    def test_allowlisted_but_not_public_is_blocked(self):
        with mock.patch.dict(os.environ, APPROVED):
            for level in ("restricted", "confidential", None, "", "Public-ish"):
                self.assertFalse(
                    auth.is_cloud_processing_authorized(fx.fictional_invention(level)), level)

    def test_allowlist_parsing_is_strict(self):
        env = {"GEMINI_APPROVED_INVENTION_IDS":
               f" not-a-uuid , {fx.INVENTION_ID.upper()} ; ,"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(auth.approved_invention_ids(), frozenset({fx.INVENTION_ID}))
        invention = fx.fictional_invention("public")
        invention["id"] = None
        with mock.patch.dict(os.environ, APPROVED):
            self.assertFalse(auth.is_cloud_processing_authorized(invention))

    def test_blocked_before_any_client_is_created(self):
        with mock.patch.object(auth, "GeminiClient") as gemini:
            with self.assertRaises(CloudProcessingNotAuthorized) as caught:
                agent.build_profile_from_processed(cloud_processing_consent=True, processed=fx.processed_result("public"))
        gemini.assert_not_called()
        self.assertIn("have not been changed", str(caught.exception))

    def test_injected_client_cannot_bypass_authorization(self):
        for level in ("public", "restricted", "confidential"):
            client = FakeGemini([fx.comprehensive_json()])
            env = APPROVED if level != "public" else {}
            with mock.patch.dict(os.environ, env):
                with self.assertRaises(CloudProcessingNotAuthorized):
                    agent.build_profile_from_processed(cloud_processing_consent=True, processed=
                        fx.processed_result(level), ai_client=client)
            self.assertEqual(client.calls, [], level)

    def test_confidentiality_never_modified(self):
        processed = fx.processed_result("restricted")
        with self.assertRaises(CloudProcessingNotAuthorized):
            agent.build_profile_from_processed(cloud_processing_consent=True, processed=processed)
        self.assertEqual(processed.invention["confidentiality"], "restricted")


# ---------------------------------------------------------------------------
# Qwen removal
# ---------------------------------------------------------------------------

class NoQwenTests(unittest.TestCase):
    def test_qwen_client_module_removed(self):
        self.assertIsNone(importlib.util.find_spec("app.services.qwen_client"))
        self.assertIsNone(importlib.util.find_spec("app.services.ai_provider"))

    def test_no_qwen_or_ollama_in_backend_or_frontend(self):
        offenders = []
        for folder in (ROOT / "backend" / "app", ROOT / "frontend"):
            for path in folder.rglob("*"):
                if path.suffix in {".py", ".js", ".html", ".txt"}:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                    if re.search(r"qwen|ollama", text, re.I):
                        offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_no_gemini_secrets_in_frontend(self):
        for path in (ROOT / "frontend").rglob("*"):
            if path.suffix in {".js", ".html"}:
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertNotRegex(text, r"GEMINI|generativelanguage|AIza", str(path))


# ---------------------------------------------------------------------------
# Gemini profiling pipeline (fake client)
# ---------------------------------------------------------------------------

@mock.patch.dict(os.environ, {**CLEAN_ENV, **APPROVED}, clear=True)
class GeminiPipelineTests(unittest.TestCase):
    def test_single_request_full_profile(self):
        client = FakeGemini([fx.comprehensive_json()])
        result = agent.build_profile_from_processed(cloud_processing_consent=True, processed=fx.processed_result(), ai_client=client)

        self.assertEqual(len(client.calls), 1, "expected one comprehensive request")
        self.assertEqual(client.calls[0][0], "FlatProfileExtraction")
        self.assertEqual(result.provider, "gemini")
        self.assertEqual(result.included_documents, [fx.RELEVANT])
        self.assertEqual(result.excluded_documents, [fx.UNRELATED])

        profile = result.profile
        components = {c.value: c for c in profile.technology.components}
        self.assertEqual(set(components), {
            "acrylic housing", "gel pad", "photodiode sensor", "ESP32 microcontroller"})
        self.assertTrue(all(c.classification == "document_fact" for c in components.values()))
        self.assertEqual(components["ESP32 microcontroller"].evidence[0].page, 1)

        lumens = profile.development.experimental_results[0]
        self.assertEqual(lumens.classification, "inference")
        self.assertTrue(lumens.explanation.startswith("UNVERIFIED"))
        self.assertEqual(profile.development.technical_limitations[0].classification, "missing")

        self.assertEqual(profile.identity.inventors[0].value, "Test Inventor A")
        self.assertTrue(any(w.startswith("AI provider: Google Gemini")
                            for w in profile.quality_warnings))
        # Full documents (not samples) were sent: page 2 content is present.
        self.assertIn("41 nights", client.calls[0][1])
        # Round-trips through the unchanged public schema (draft-save path).
        InventionAIProfile.model_validate(profile.model_dump(mode="json"))

    def test_targeted_repair_runs_only_when_needed(self):
        payload = fx.comprehensive_payload()
        payload["identity"]["concise_summary"] = None
        repair = {"concise_summary": {
            "value": "Glowfern is a self-powered marker using engineered moss in a "
                     "sealed housing, tested as a laboratory prototype for 41 nights.",
            "classification": "inference"}}
        client = FakeGemini([json.dumps(fx.to_flat(payload)), json.dumps(repair)])
        result = agent.build_profile_from_processed(cloud_processing_consent=True, processed=fx.processed_result(), ai_client=client)
        self.assertEqual([c[0] for c in client.calls],
                         ["FlatProfileExtraction", "FocusedExtraction"])
        self.assertIn("41 nights", result.profile.identity.concise_summary.value)

    def test_repair_fills_problem_objective_and_industries(self):
        payload = fx.comprehensive_payload()
        del payload["problem_solution"]
        del payload["applications"]
        repair = {
            "problem": {"value": "Path markers usually need external power.",
                        "classification": "inference",
                        "explanation": "Synthesized from glowfern_report.pdf."},
            "objective": {"value": "A self-powered bioluminescent marker.",
                          "classification": "inference"},
            "industries": [
                {"value": "Outdoor lighting", "classification": "inference"},
                {"value": "outdoor  lighting", "classification": "inference"},
                {"value": "Landscaping", "classification": "inference"},
            ],
        }
        client = FakeGemini([json.dumps(fx.to_flat(payload)), json.dumps(repair)])
        result = agent.build_profile_from_processed(cloud_processing_consent=True, processed=fx.processed_result(), ai_client=client)

        self.assertEqual([c[0] for c in client.calls],
                         ["FlatProfileExtraction", "FocusedExtraction"])
        targets = re.search(r"TARGET FIELDS:\s*(\[.*?\])", client.calls[1][1]).group(1)
        # the whole problem_solution section is missing, so all four statements are targets
        self.assertEqual(set(json.loads(targets)), {"problem", "objective", "solution",
                                                    "working_mechanism", "industries", "use_cases"})
        ps = result.profile.problem_solution
        self.assertEqual(ps.problem.value, "Path markers usually need external power.")
        self.assertEqual(ps.problem.classification, "inference")
        self.assertEqual(ps.objective.classification, "inference")
        self.assertEqual([c.value for c in result.profile.applications.industries],
                         ["Outdoor lighting", "Landscaping"])

    def test_repair_fills_empty_use_cases_without_moving_customers(self):
        payload = fx.comprehensive_payload()
        payload["applications"] = {
            "industries": [{"value": "Outdoor lighting", "classification": "inference"}],
            "target_customers": [{"value": "Parks departments", "classification": "inference"}],
        }
        repair = {"use_cases": [
            {"value": "Marking footpaths at night", "classification": "inference"},
            {"value": "marking footpaths at  night", "classification": "inference"},
        ]}
        client = FakeGemini([json.dumps(fx.to_flat(payload)), json.dumps(repair)])
        result = agent.build_profile_from_processed(cloud_processing_consent=True, processed=fx.processed_result(), ai_client=client)
        targets = re.search(r"TARGET FIELDS:\s*(\[.*?\])", client.calls[1][1]).group(1)
        self.assertEqual(json.loads(targets), ["use_cases"])
        applications = result.profile.applications
        self.assertEqual([c.value for c in applications.use_cases], ["Marking footpaths at night"])
        self.assertEqual([c.value for c in applications.target_customers], ["Parks departments"])
        self.assertIn("use_cases: WHERE or FOR WHAT", client.calls[1][1])

    def test_repair_fills_empty_partner_types_as_recommendations(self):
        payload = fx.comprehensive_payload()
        del payload["partner_requirements"]
        repair = {"potential_partner_types": [
            {"value": "Contract electronics manufacturer", "classification": "recommendation"},
            {"value": "contract electronics  manufacturer", "classification": "recommendation"},
            {"value": "Field-testing laboratory", "classification": "recommendation"},
        ]}
        client = FakeGemini([json.dumps(fx.to_flat(payload)), json.dumps(repair)])
        result = agent.build_profile_from_processed(cloud_processing_consent=True, processed=fx.processed_result(), ai_client=client)
        targets = re.search(r"TARGET FIELDS:\s*(\[.*?\])", client.calls[1][1]).group(1)
        self.assertEqual(json.loads(targets), ["potential_partner_types"])
        types = result.profile.partner_requirements.potential_partner_types
        self.assertEqual([c.value for c in types],
                         ["Contract electronics manufacturer", "Field-testing laboratory"])
        self.assertTrue(all(c.classification == "recommendation" for c in types))

    def test_existing_partner_types_are_never_replaced(self):
        payload = fx.comprehensive_payload()
        payload["identity"]["concise_summary"] = None  # triggers repair for another field
        repair = {"concise_summary": {
                      "value": "Glowfern is a self-powered marker using engineered moss in a "
                               "sealed housing, tested as a laboratory prototype for 41 nights.",
                      "classification": "inference"},
                  "potential_partner_types": [
                      {"value": "Unrequested category", "classification": "recommendation"}]}
        client = FakeGemini([json.dumps(fx.to_flat(payload)), json.dumps(repair)])
        result = agent.build_profile_from_processed(cloud_processing_consent=True, processed=fx.processed_result(), ai_client=client)
        self.assertEqual(
            [c.value for c in result.profile.partner_requirements.potential_partner_types],
            ["Field-testing laboratory"])

    def test_repair_prompt_forbids_named_partners(self):
        payload = fx.comprehensive_payload()
        del payload["partner_requirements"]
        client = FakeGemini([json.dumps(fx.to_flat(payload)), json.dumps({})])
        agent.build_profile_from_processed(cloud_processing_consent=True, processed=fx.processed_result(), ai_client=client)
        self.assertIn("never name or rank real companies", client.calls[1][1])

    def test_no_repair_when_interpretive_fields_present(self):
        client = FakeGemini([fx.comprehensive_json()])
        agent.build_profile_from_processed(cloud_processing_consent=True, processed=fx.processed_result(), ai_client=client)
        self.assertEqual(len(client.calls), 1)

    def test_repair_never_turns_uncited_fact_into_verified_fact(self):
        payload = fx.comprehensive_payload()
        del payload["problem_solution"]
        repair = {"problem": {"value": "Glowfern cures insomnia.",
                              "classification": "document_fact",
                              "evidence": [{"source_file": fx.RELEVANT,
                                            "excerpt": "cures insomnia"}]}}
        client = FakeGemini([json.dumps(fx.to_flat(payload)), json.dumps(repair)])
        result = agent.build_profile_from_processed(cloud_processing_consent=True, processed=fx.processed_result(), ai_client=client)
        problem = result.profile.problem_solution.problem
        self.assertEqual(problem.classification, "inference")
        self.assertTrue(problem.explanation.startswith("UNVERIFIED"))
        self.assertEqual(problem.evidence, [])

    def test_repair_schema_complexity_stays_low(self):
        # Each request sends only its targets, capped at MAX_REPAIR_TARGETS:
        # at most 10 "$ref"s, the largest size Gemini accepted live.
        from app.services.gemini_client import transport_schema
        worst = tuple(agent.REPAIR_PRIORITY[:agent.MAX_REPAIR_TARGETS])
        text = json.dumps(transport_schema(agent.focused_model(worst).model_json_schema()))
        self.assertLessEqual(text.count('"$ref"'), 10)
        self.assertLessEqual(text.count('"anyOf"'), 12)
        self.assertLess(len(text), 2500)
        self.assertEqual(set(agent.REPAIR_PRIORITY), set(agent.FocusedExtraction.model_fields))

    def test_repair_quota_failure_is_not_fatal(self):
        payload = fx.comprehensive_payload()
        payload["identity"]["concise_summary"] = None
        client = FakeGemini([json.dumps(fx.to_flat(payload)), GeminiQuotaError("quota")])
        result = agent.build_profile_from_processed(cloud_processing_consent=True, processed=fx.processed_result(), ai_client=client)
        self.assertTrue(any("repair was skipped" in w for w in result.warnings))
        self.assertEqual(result.profile.identity.concise_summary.classification,
                         "registration_fact")

    def test_primary_quota_error_propagates_without_fallback(self):
        client = FakeGemini([GeminiQuotaError("Daily free-tier quota exhausted.")])
        with self.assertRaises(GeminiQuotaError):
            agent.build_profile_from_processed(cloud_processing_consent=True, processed=fx.processed_result(), ai_client=client)
        self.assertEqual(len(client.calls), 1)

    def test_end_to_end_with_real_client_and_fake_sdk(self):
        sdk_calls = []

        class SDK:
            models = None

            def generate_content(self, *, model, contents, config):
                sdk_calls.append(model)
                return SimpleNamespace(
                    text=fx.comprehensive_json(), prompt_feedback=None,
                    candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))])

        sdk = SDK()
        sdk.models = sdk
        client = GeminiClient(confidentiality="public", sdk_client=sdk,
                              rate_limiter=FreeTierRateLimiter())
        result = agent.build_profile_from_processed(cloud_processing_consent=True, processed=fx.processed_result(), ai_client=client)
        self.assertEqual(sdk_calls, ["gemini-3.5-flash-lite"])
        self.assertEqual(client.remaining_requests_today(), 499)
        self.assertEqual(result.model, "gemini-3.5-flash-lite")

    def test_default_client_is_flash_lite(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "fake-test-key"}):
            client = auth.create_profiling_client(fx.fictional_invention("public"), None, True)
        self.assertIsInstance(client, GeminiClient)
        self.assertEqual(client.model, "gemini-3.5-flash-lite")

    def test_comparison_fixture_is_profilable(self):
        """The live comparison input itself is valid for the pipeline."""
        processed = fx.comparison_processed_result()
        self.assertTrue(auth.is_cloud_processing_authorized(processed.invention))
        context, _, warnings = agent.build_source_context(
            processed, {d.filename for d in processed.documents})
        self.assertIn("ESP32-C3", context)
        self.assertEqual(warnings, [])


# ---------------------------------------------------------------------------
# Flat claims list -> unchanged InventionAIProfile
# ---------------------------------------------------------------------------

def flat(claims, **extra):
    return agent.FlatProfileExtraction.model_validate({"claims": claims, **extra})


class FlatAssemblyTests(unittest.TestCase):
    def test_field_paths_cover_every_profile_claim_field(self):
        self.assertEqual(len(agent.CLAIM_FIELD_PATHS), 42)
        self.assertEqual(len(set(agent.CLAIM_FIELD_PATHS)), 42)
        for path in agent.CLAIM_FIELD_PATHS:
            section, name = path.split(".")
            value = getattr(getattr(InventionAIProfile(), section), name)
            if path in agent.LIST_CLAIM_PATHS:
                self.assertIsInstance(value, list, path)
            else:
                self.assertIsNone(value, path)
        self.assertIn("technology.components", agent.LIST_CLAIM_PATHS)
        self.assertIn("development.prototype_status", agent.SINGLE_CLAIM_PATHS)

    def test_unknown_field_is_rejected_by_schema(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            flat([{"field": "identity.secret_notes", "value": "x",
                   "classification": "inference"}])

    def test_list_fields_collect_items_and_merge_duplicates(self):
        extraction = flat(fx.to_flat({"document_relevance": [], "technology": {"components": [
            fx.fact("gel pad", "moisture-retaining gel pad"),
            fx.fact("Gel Pad", "moisture-retaining gel pad"),
            fx.fact("acrylic housing", "a sealed acrylic housing"),
        ]}})["claims"])
        profile, warnings = agent.assemble_flat_profile(extraction, index())
        self.assertEqual([c.value for c in profile.technology.components],
                         ["gel pad", "acrylic housing"])
        self.assertEqual(warnings, [])

    def test_single_field_keeps_verified_candidate_and_reports_others(self):
        extraction = flat([
            {"field": "development.prototype_status", "value": "Field-proven product",
             "classification": "inference"},
            {"field": "development.prototype_status", "value": "Laboratory prototype",
             "classification": "document_fact",
             "evidence": [{"source_file": fx.RELEVANT, "page": 2,
                           "excerpt": "A laboratory prototype glowed for 41 nights"}]},
        ])
        profile, warnings = agent.assemble_flat_profile(extraction, index())
        self.assertEqual(profile.development.prototype_status.value, "Laboratory prototype")
        self.assertEqual(len(warnings), 1)
        self.assertIn("Field-proven product", warnings[0])
        self.assertIn("profile.development.prototype_status", warnings[0])

    def test_blank_value_reported_not_used(self):
        extraction = flat([{"field": "identity.title", "value": "   ",
                            "classification": "inference"}])
        profile, warnings = agent.assemble_flat_profile(extraction, index())
        self.assertIsNone(profile.identity.title)
        self.assertIn("malformed", warnings[0])

    def test_suggested_trl_bounds_enforced_locally(self):
        profile, _ = agent.assemble_flat_profile(flat([], suggested_trl=4), index())
        self.assertEqual(profile.readiness.suggested_trl, 4)
        profile, warnings = agent.assemble_flat_profile(flat([], suggested_trl=15), index())
        self.assertIsNone(profile.readiness.suggested_trl)
        self.assertIn("TRL", warnings[0])

    def test_uncited_document_fact_downgraded_during_validation(self):
        token = agent._ACTIVE_SOURCE_INDEX.set(index())
        try:
            extraction = flat([{"field": "development.experimental_results",
                                "value": "Glows for a full year",
                                "classification": "document_fact"}])
        finally:
            agent._ACTIVE_SOURCE_INDEX.reset(token)
        claim = extraction.claims[0]
        self.assertEqual(claim.classification, "inference")
        self.assertTrue(claim.explanation.startswith("UNVERIFIED"))

    def test_prompt_requires_grounded_interpretive_fields(self):
        text = agent.GEMINI_EXTRACTION_INSTRUCTIONS
        for phrase in ("problem_solution.problem", "working_mechanism",
                       "applications.use_cases", "required_capabilities",
                       "potential_partner_types", "INTERPRETIVE CONTENT RULES",
                       "never introduce facts absent from the sources"):
            self.assertIn(phrase, text)

    def test_prompt_requires_atomic_items(self):
        text = agent.GEMINI_EXTRACTION_INSTRUCTIONS
        self.assertIn("ATOMIC ITEMS", text)
        self.assertIn("never merge several results, limitations", text)
        self.assertIn("SEPARATE claim", text)

    def test_prompt_preserves_novelty_hedges(self):
        text = agent.GEMINI_EXTRACTION_INSTRUCTIONS
        self.assertIn("novelty is the inventors' CLAIM", text)
        self.assertIn("To the authors' knowledge", text)
        self.assertIn("never strengthen it", text)

    def test_prompt_separates_use_cases_from_customers_and_industries(self):
        text = agent.GEMINI_EXTRACTION_INSTRUCTIONS
        for phrase in ("use_cases: WHERE or FOR WHAT", "target_customers: WHO",
                       "industries: commercial industry SECTORS",
                       '("target settings include ...") belong HERE',
                       "Do not leave use_cases empty"):
            self.assertIn(phrase, text)

    def test_interpretive_claims_keep_their_labels_through_verification(self):
        extraction = flat([
            {"field": "problem_solution.problem",
             "value": "Path markers need power; Glowfern needs none.",
             "classification": "inference",
             "explanation": "Synthesized from glowfern_report.pdf."},
            {"field": "partner_requirements.required_capabilities",
             "value": "Outdoor field-testing capability",
             "classification": "recommendation"},
        ])
        profile, _ = agent.assemble_flat_profile(extraction, index())
        agent.validate_claim_evidence(profile, index(), fx.fictional_invention())
        problem = profile.problem_solution.problem
        partner = profile.partner_requirements.required_capabilities[0]
        self.assertEqual((problem.classification, partner.classification),
                         ("inference", "recommendation"))
        self.assertFalse((problem.explanation or "").startswith("UNVERIFIED"))
        self.assertEqual(problem.value, "Path markers need power; Glowfern needs none.")

    def test_prompt_lists_single_and_list_fields(self):
        text = agent.GEMINI_EXTRACTION_INSTRUCTIONS
        self.assertIn("development.prototype_status", text)
        self.assertIn("technology.components", text)
        self.assertNotIn("{single_fields}", text)


# ---------------------------------------------------------------------------
# Draft safety and API error mapping (Supabase fully mocked)
# ---------------------------------------------------------------------------

FAKE_SUPABASE = {
    "SUPABASE_URL": "https://example.invalid",
    "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_fake",
    "SUPABASE_SECRET_KEY": "sb_secret_fake",
}


@mock.patch.dict(os.environ, FAKE_SUPABASE)
class DraftSafetyTests(unittest.TestCase):
    def run_generate(self, error, existing):
        from app.services import profile_service as ps

        service = ps.ProfileService()
        service._owner_id = mock.AsyncMock(return_value=fx.OWNER_ID)
        service._get_draft_row = mock.AsyncMock(return_value=existing)
        service._insert_draft = mock.AsyncMock()
        service._update_draft = mock.AsyncMock()
        with mock.patch.object(ps, "generate_invention_profile",
                               mock.AsyncMock(side_effect=error)):
            with self.assertRaises(type(error)):
                asyncio.run(service.generate_draft(
                    fx.INVENTION_ID, "token",
                    regenerate=existing is not None,
                    expected_updated_at=existing and existing["updated_at"]))
        service._insert_draft.assert_not_awaited()
        service._update_draft.assert_not_awaited()

    def test_blocked_generation_writes_nothing(self):
        self.run_generate(CloudProcessingNotAuthorized("blocked"), None)

    def test_quota_error_never_overwrites_existing_draft(self):
        existing = {"updated_at": "2026-11-24T10:00:00+00:00", "generation_number": 1}
        self.run_generate(GeminiQuotaError("quota"), existing)


class ApiErrorMappingTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import app.main
        self.client = TestClient(app.main.app)

    def post_generate(self, error):
        service = mock.Mock()
        service.generate_draft = mock.AsyncMock(side_effect=error)
        with mock.patch("app.api.profiles.ProfileService", return_value=service):
            return self.client.post(
                f"/api/inventions/{fx.INVENTION_ID}/profile/generate",
                headers={"Authorization": "Bearer fake"})

    def test_blocked_is_403_with_clear_message(self):
        response = self.post_generate(CloudProcessingNotAuthorized(auth.BLOCKED_MESSAGE))
        self.assertEqual(response.status_code, 403)
        self.assertIn("not authorized", response.json()["detail"])

    def test_quota_is_429(self):
        response = self.post_generate(GeminiQuotaError("quota"))
        self.assertEqual(response.status_code, 429)
        self.assertIn("has not been changed", response.json()["detail"])

    def test_generic_failure_message_has_no_ollama_reference(self):
        response = self.post_generate(RuntimeError("boom"))
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("Ollama", response.json()["detail"])

    def test_submission_routes_are_registered(self):
        # Previously 404 (router not included); now requires authentication.
        response = self.client.post(
            f"/api/inventions/{fx.INVENTION_ID}/profile/submit",
            json={"expected_updated_at": "2026-11-24T10:00:00+00:00"})
        self.assertNotEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
