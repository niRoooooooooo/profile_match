"""Offline tests on the larger FICTIONAL Tidewell set. No live AI calls."""

import json
import os
import unittest
from unittest import mock

import _fixtures as fx
import _large_fixture as lf

from app.agents import profiling_agent as agent
from app.schemas.profile import InventionAIProfile
from app.services.cloud_authorization import CloudProcessingNotAuthorized

CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith(("GEMINI_", "PROFILING_", "CLOUD_PROCESSING_"))}
APPROVED = {"GEMINI_APPROVED_INVENTION_IDS": lf.LARGE_INVENTION_ID}


class FakeGemini:
    provider = "gemini"
    model = "gemini-3.5-flash-lite"

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def remaining_requests_today(self):
        return 100

    def generate_structured(self, prompt, response_model, **kwargs):
        self.calls.append((response_model.__name__, prompt))
        item = self.payloads.pop(0)
        return response_model.model_validate_json(item)


def fact(field, value, source, excerpt, page=None, section=None):
    return {"field": field, "value": value, "classification": "document_fact",
            "evidence": [{"source_file": source, "page": page, "section": section,
                          "excerpt": excerpt}]}


def infer(field, value, kind="inference", explanation=None):
    return {"field": field, "value": value, "classification": kind,
            "explanation": explanation}


def simulated_response():
    """A realistic, complete flat answer with deliberate citation quirks."""
    T, S, M = lf.TECH, lf.TESTS, lf.MEMO
    claims = [
        infer("identity.concise_summary",
              "Tidewell is a solar-powered desalination cartridge that uses a graphene-oxide "
              "membrane at low pressure. Prototype v3 reached 97.2% salt rejection over 500 "
              "hours in laboratory tests; no outdoor field pilot has been completed."),
        infer("identity.detailed_summary",
              "Tidewell combines a graphene-oxide membrane stack with solar-powered low-pressure "
              "pumping. Prototype v3 met all laboratory targets; no outdoor field pilot has "
              "been completed."),
        fact("problem_solution.problem", "Small coastal communities often lack reliable grid power",
             T, "Small coastal communities often lack reliable grid power", page=1),
        infer("problem_solution.solution",
              "A low-pressure graphene-oxide membrane cartridge powered only by solar energy."),
        fact("problem_solution.working_mechanism",
             "Salt ions are rejected by size exclusion and charge repulsion", T,
             "reject salt ions by size exclusion and charge repulsion", page=3),
        fact("problem_solution.objective", "Low-energy household-maintainable desalination unit", T,
             "aims to provide a low-energy desalination unit", page=1),
        fact("technology.primary_domain", "Water Technology", T, "desalination", page=1),
        fact("technology.components", "graphene-oxide membrane stack", T,
             "graphene-oxide membrane stack", page=2),
        fact("technology.components", "titanium mesh pre-filter", T, "titanium mesh pre-filter", page=2),
        fact("technology.components", "peristaltic micro-pump", T, "peristaltic micro-pump", page=2),
        fact("technology.components", "20 W solar panel", T, "20 W solar panel", page=2),
        fact("technology.components", "conductivity sensor", T, "conductivity sensor", page=2),
        fact("technology.components", "LoRa radio module", T, "LoRa radio module", page=2),
        fact("technology.novelty", "First cartridge combining graphene-oxide membrane with solar-only "
             "low-pressure pumping (authors' claim)", T,
             "the first cartridge to combine a graphene-oxide membrane with solar-only", page=5),
        # QUIRK: wrong page (should be 4) -> must be corrected, not discarded.
        fact("development.prototype_status", "Prototype v3 is a sealed, field-deployable unit", T,
             "Prototype v3 is a sealed, field-deployable unit", page=2),
        fact("development.testing_methods", "Laboratory seawater at 35 g/L", S,
             "Laboratory seawater, 35 g/L", page=1),
        # QUIRK: table row quoted with different spacing -> verified via compact match.
        fact("development.experimental_results", "Salt rejection 97.2 %", S,
             "Salt rejection 97.2 %", page=1),
        fact("development.experimental_results", "Water flux 14 L/m2/h", S, "Water flux 14 L/m2/h", page=1),
        fact("development.experimental_results", "Specific energy 1.8 kWh/m3", S,
             "Specific energy 1.8 kWh/m3", page=1),
        fact("development.experimental_results", "Continuous operation for 500 hours", S,
             "Continuous operation 500 hours", page=1),
        # QUIRK: PDF hyphenation "Bio-\\nfouling" in source.
        fact("development.technical_limitations", "Biofouling reduced water flux by 22% after 300 hours",
             S, "Biofouling reduced water flux by 22% after 300 hours", page=2),
        fact("development.technical_limitations", "Not tested on brackish groundwater", S,
             "has not been tested on brackish groundwater", page=2),
        fact("development.technical_limitations", "No outdoor field pilot has been completed", S,
             "no outdoor field pilot has been completed", page=2),
        fact("readiness.justification", "The team assesses the technology at TRL 4", S,
             "the team assesses the technology at TRL 4", page=2),
        fact("intellectual_property.patent_status", "PCT application filed on 14 May 2026", M,
             "was filed on 14 May 2026", section="Intellectual property"),
        fact("intellectual_property.ownership_claims",
             "IP is jointly owned by Harlow Polytechnic and Meridian Coastal Trust", M,
             "The IP is jointly owned by Harlow Polytechnic and the project sponsor",
             section="Intellectual property"),
        fact("intellectual_property.licensing_restrictions",
             "Sponsor holds a 12-month right of first negotiation", M,
             "right of first negotiation for an exclusive licence for 12 months",
             section="Intellectual property"),
        fact("intellectual_property.disclosed_prior_art", "Okafor et al. (2019) graphene-oxide membranes",
             T, "Prior work by Okafor et al. (2019)", page=5),
        fact("commercialization.documented_costs", "USD 210 per cartridge at 500 units", M,
             "USD 210 per cartridge at a volume of 500", section="Commercial notes"),
        fact("commercialization.maintenance_requirements", "Replace pre-filter every 3 months", M,
             "must be replaced every 3 months", section="Commercial notes"),
        fact("applications.use_cases", "Coastal villages", M, "coastal villages", section="Commercial notes"),
        fact("applications.use_cases", "Disaster-relief shelters", M, "disaster-relief shelters",
             section="Commercial notes"),
        fact("applications.use_cases", "Small island resorts", M, "small island resorts",
             section="Commercial notes"),
        infer("applications.industries", "Water treatment"),
        fact("gaps.regulatory_questions", "No drinking-water certification obtained; NSF/ANSI 61 planned",
             M, "No drinking-water certification has been obtained yet",
             section="Regulatory status and next steps"),
        fact("partner_requirements.required_capabilities", "Scaled membrane manufacturing", M,
             "scaled membrane manufacturing", section="Regulatory status and next steps"),
        fact("partner_requirements.required_capabilities", "Running a 12-month outdoor field pilot", M,
             "run a 12-month outdoor field pilot", section="Regulatory status and next steps"),
        infer("partner_requirements.potential_partner_types", "Membrane manufacturers", "recommendation"),
        infer("partner_requirements.potential_partner_types", "Field-testing organisations", "recommendation"),
    ]
    return {
        "document_relevance": [
            {"filename": lf.TECH, "relevance": "relevant", "explanation": "Technical report."},
            {"filename": lf.TESTS, "relevance": "relevant", "explanation": "Test campaign."},
            {"filename": lf.MEMO, "relevance": "relevant", "explanation": "IP and commercial memo."},
            {"filename": lf.UNRELATED, "relevance": "unrelated", "explanation": "Parking policy."},
        ],
        "claims": claims,
        "suggested_trl": 4,
        "discrepancies": [
            {"field": "readiness.reported_trl", "registration_value": "5", "document_value": "TRL 4",
             "evidence": [{"source_file": lf.TESTS, "page": 2,
                           "excerpt": "the team assesses the technology at TRL 4"}]},
            {"field": "identity.title", "registration_value": "x", "document_value": "y",
             "evidence": []},
        ],
        "missing_information": ["Supply chain information is not provided."],
        "quality_warnings": [],
    }


def run(payload, confidentiality="public"):
    client = FakeGemini([json.dumps(payload)])
    result = agent.build_profile_from_processed(cloud_processing_consent=True, processed=
        lf.large_processed_result(confidentiality), ai_client=client)
    return result, client


class FixtureIntegrityTests(unittest.TestCase):
    def test_every_ground_truth_item_is_achievable_from_sources(self):
        source = lf.source_text().lower()
        for component in lf.LARGE_TRUTH["components"]:
            self.assertIn(component, source)
        for name, needles in lf.LARGE_TRUTH["key_facts"].items():
            for needle in needles:
                self.assertIn(needle, source.replace("bio-\nfouling", "biofouling"), name)
        for term in lf.LARGE_TRUTH["application_terms"] + lf.LARGE_TRUTH["partner_terms"]:
            self.assertIn(term, source)

    def test_set_is_materially_larger_than_glowfern(self):
        small = sum(len(t) for c in fx.COMPARISON_DOCS.values() for _, _, t in c)
        large = sum(len(t) for c in lf.LARGE_DOCS.values() for _, _, t in c)
        self.assertGreater(large, 3 * small)
        self.assertEqual(sum(len(c) for c in lf.LARGE_DOCS.values()), 12)

    def test_whole_set_fits_without_sampling(self):
        processed = lf.large_processed_result()
        names = {d.filename for d in processed.documents}
        context, _, warnings = agent.build_source_context(processed, names)
        self.assertEqual(warnings, [])
        for name in names:
            self.assertIn(f"FILE: {name}", context)
        self.assertIn("Appendix C", context)  # later pages are not truncated


@mock.patch.dict(os.environ, CLEAN_ENV, clear=True)
class LargeAuthorizationTests(unittest.TestCase):
    def test_large_set_blocked_until_allowlisted(self):
        with self.assertRaises(CloudProcessingNotAuthorized):
            run(simulated_response())
        with mock.patch.dict(os.environ, APPROVED):
            for level in ("restricted", "confidential"):
                with self.assertRaises(CloudProcessingNotAuthorized):
                    run(simulated_response(), level)


class LargePipelineTests(unittest.TestCase):
    def setUp(self):
        # Class-level patch.dict does not cover setUp; patch for each test.
        self.enterContext(mock.patch.dict(os.environ, {**CLEAN_ENV, **APPROVED}, clear=True))
        self.result, self.client = run(simulated_response())
        self.profile = self.result.profile
        self.metrics = lf.evaluate_large(self.result)

    def test_single_request_and_valid_schema(self):
        self.assertEqual([c[0] for c in self.client.calls], ["FlatProfileExtraction"])
        InventionAIProfile.model_validate(self.profile.model_dump(mode="json"))
        json.loads(json.dumps(self.profile.model_dump(mode="json")))

    def test_all_quality_criteria_pass_for_complete_answer(self):
        verdict = lf.large_verdict(self.metrics)
        self.assertEqual([k for k, ok in verdict.items() if not ok], [], self.metrics)
        self.assertEqual(self.metrics["key_fact_recall"], 1.0, self.metrics["missed_facts"])

    def test_wrong_page_corrected_and_quirky_quotes_verified(self):
        prototype = self.profile.development.prototype_status
        self.assertEqual(prototype.classification, "document_fact")
        self.assertEqual(prototype.evidence[0].page, 4)
        results = {c.value: c for c in self.profile.development.experimental_results}
        self.assertEqual(results["Salt rejection 97.2 %"].classification, "document_fact")
        fouling = self.profile.development.technical_limitations[0]
        self.assertEqual(fouling.classification, "document_fact")
        self.assertTrue(any("corrected" in w for w in self.result.warnings))

    def test_discrepancy_with_evidence_kept_and_without_dropped(self):
        self.assertEqual([d.field for d in self.profile.discrepancies], ["readiness.reported_trl"])
        self.assertTrue(any("discrepancy in 'identity.title'" in w for w in self.result.warnings))

    def test_registration_values_preserved_as_declarations(self):
        self.assertEqual(self.profile.readiness.reported_trl, 5)
        self.assertEqual(self.profile.readiness.suggested_trl, 4)
        self.assertEqual([c.value for c in self.profile.identity.inventors],
                         ["Test Inventor B", "Test Inventor C"])

    def test_missing_data_stays_missing(self):
        self.assertIsNone(self.profile.commercialization.supply_chain)
        self.assertIn("Supply chain information is not provided.",
                      self.profile.missing_information)
        self.assertEqual(self.result.excluded_documents, [lf.UNRELATED])


@mock.patch.dict(os.environ, {**CLEAN_ENV, **APPROVED}, clear=True)
class LargeFailureModeTests(unittest.TestCase):
    def with_extra(self, *claims):
        payload = simulated_response()
        payload["claims"] = payload["claims"] + list(claims)
        return run(payload)[0]

    def test_fabricated_certification_is_unverified_and_flagged(self):
        result = self.with_extra(fact(
            "gaps.regulatory_questions", "The cartridge is certified to NSF/ANSI 61",
            lf.MEMO, "certified to NSF/ANSI 61 in 2026", section="Regulatory status and next steps"))
        claim = [c for c in result.profile.gaps.regulatory_questions if "is certified" in c.value][0]
        self.assertEqual(claim.classification, "inference")
        self.assertTrue(claim.explanation.startswith("UNVERIFIED"))
        verdict = lf.large_verdict(lf.evaluate_large(result))
        self.assertFalse(verdict["no_injection_or_reversal"])

    def test_injection_value_detected(self):
        result = self.with_extra(infer("readiness.verification_needed", "Rated TRL 9 and CE certified"))
        self.assertFalse(lf.large_verdict(lf.evaluate_large(result))["no_injection_or_reversal"])

    def test_invented_number_detected(self):
        result = self.with_extra(infer("commercialization.product_concept",
                                       "Produces 40 litres per day for a family"))
        metrics = lf.evaluate_large(result)
        self.assertIn("profile.commercialization.product_concept: 40", metrics["unsupported_numbers"])

    def test_superseded_prototype_value_detected(self):
        result = self.with_extra(fact("development.experimental_results", "91% salt rejection",
                                      lf.TECH, "it achieved 91% salt rejection", page=4))
        self.assertTrue(lf.evaluate_large(result)["superseded_v1_in_results"])

    def test_claim_from_unrelated_document_removed(self):
        result = self.with_extra(fact("commercialization.supply_chain", "Permits renewed each September",
                                      lf.UNRELATED, "renewed each September", section="Parking"))
        self.assertIsNone(result.profile.commercialization.supply_chain.value)
        self.assertEqual(result.profile.commercialization.supply_chain.classification, "missing")
        self.assertFalse(lf.evaluate_large(result)["supply_chain_invented"])

    def test_paraphrased_quote_kept_but_unverified(self):
        result = self.with_extra(fact("development.testing_methods", "Tested with lab seawater",
                                      lf.TESTS, "tests used synthetic ocean water at 35 grams", page=1))
        claim = next(c for c in result.profile.development.testing_methods
                     if c.value == "Tested with lab seawater")
        self.assertEqual(claim.classification, "inference")
        self.assertTrue(claim.explanation.startswith("UNVERIFIED"))

    def test_incomplete_answer_fails_completeness_criteria(self):
        payload = simulated_response()
        payload["claims"] = [c for c in payload["claims"]
                             if c["field"] not in ("development.experimental_results",
                                                   "technology.components")]
        client = FakeGemini([json.dumps(payload), json.dumps({})])
        result = agent.build_profile_from_processed(cloud_processing_consent=True, processed=lf.large_processed_result(), ai_client=client)
        metrics = lf.evaluate_large(result)
        self.assertFalse(lf.large_verdict(metrics)["components"])
        # Facts only stated in the removed results are reported as missed.
        self.assertTrue({"flux 14", "energy 1.8"} <= set(metrics["missed_facts"]),
                        metrics["missed_facts"])
        self.assertLess(metrics["key_fact_recall"], 1.0)


if __name__ == "__main__":
    unittest.main()
