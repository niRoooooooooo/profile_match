"""Offline tests for GeminiClient. No network calls; the SDK is faked."""

import json
import os
import re
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

import _fixtures  # noqa: F401  (adds backend to sys.path)
from pydantic import BaseModel

from app.services.gemini_client import (
    FreeTierRateLimiter,
    GeminiClient,
    GeminiConfigurationError,
    GeminiError,
    GeminiPrivacyError,
    GeminiQuotaError,
    GeminiResponseError,
    transport_schema,
)

CLEAN_ENV = {
    k: v for k, v in os.environ.items()
    if not k.startswith(("GEMINI_", "PROFILING_", "CLOUD_PROCESSING_"))
}


class Small(BaseModel):
    name: str


def response(text, finish="STOP"):
    return SimpleNamespace(
        text=text,
        prompt_feedback=None,
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=finish))],
    )


class FakeSDK:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []
        self.models = self

    def generate_content(self, *, model, contents, config):
        self.calls.append(SimpleNamespace(model=model, contents=contents, config=config))
        item = self.outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeAPIError(Exception):
    def __init__(self, code, message):
        super().__init__(f"{code} {message}")
        self.code = code
        self.status = "RESOURCE_EXHAUSTED" if code == 429 else "ERR"
        self.message = message


def make(outputs, **kwargs):
    sdk = FakeSDK(outputs)
    client = GeminiClient(
        confidentiality="public",
        sdk_client=sdk,
        rate_limiter=FreeTierRateLimiter(),
        **kwargs,
    )
    return client, sdk


@mock.patch.dict(os.environ, CLEAN_ENV, clear=True)
class PrivacyAndConfigTests(unittest.TestCase):
    def test_refuses_restricted_confidential_and_unknown(self):
        for level in ("restricted", "confidential", None, "", "PUBLIC-ish"):
            with self.assertRaises(GeminiPrivacyError):
                GeminiClient(confidentiality=level, sdk_client=FakeSDK([]))

    def test_rejects_models_outside_free_tier_allowlist(self):
        with self.assertRaises(GeminiConfigurationError):
            GeminiClient(confidentiality="public", model="gemini-ultra-paid",
                         sdk_client=FakeSDK([]))

    def test_unapproved_models_require_explicit_approval(self):
        from app.services import gemini_client as gc
        unapproved = gc.FreeTierModel(rpm=1, rpd=1, tpm=1000, approved_for_profiling=False)
        with mock.patch.dict(gc.FREE_TIER_MODELS, {"gemini-test-candidate": unapproved}):
            with self.assertRaises(GeminiConfigurationError):
                GeminiClient(confidentiality="public", model="gemini-test-candidate",
                             sdk_client=FakeSDK([]))
            # Comparison tooling may bypass approval explicitly.
            GeminiClient(confidentiality="public", model="gemini-test-candidate",
                         sdk_client=FakeSDK([]), require_profiling_approval=False)

    def test_default_model_is_approved_flash_lite(self):
        client = GeminiClient(confidentiality="public", sdk_client=FakeSDK([]))
        self.assertEqual(client.model, "gemini-3.5-flash-lite")
        self.assertEqual((client.rpm, client.rpd, client.tpm), (15, 500, 250_000))

    def test_hydrogen_remains_selectable_alternative(self):
        with mock.patch.dict(os.environ, {"GEMINI_MODEL": "gemini-4-hydrogen"}):
            client = GeminiClient(confidentiality="public", sdk_client=FakeSDK([]))
        self.assertEqual(client.model, "gemini-4-hydrogen")
        self.assertEqual((client.rpm, client.rpd), (5, 20))

    def test_env_overrides_can_only_lower_limits(self):
        with mock.patch.dict(os.environ, {"GEMINI_RPM_LIMIT": "99", "GEMINI_RPD_LIMIT": "10"}):
            client = GeminiClient(confidentiality="public", sdk_client=FakeSDK([]))
        self.assertEqual((client.rpm, client.rpd), (15, 10))

    def test_missing_key_is_reported_without_value(self):
        with self.assertRaises(GeminiConfigurationError) as caught:
            GeminiClient(confidentiality="public")
        self.assertIn("GEMINI_API_KEY", str(caught.exception))

    def test_key_never_in_repr(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "fake-test-key-123"}):
            client = GeminiClient(confidentiality="public")
        self.assertNotIn("fake-test-key-123", repr(client))
        self.assertNotIn("fake-test-key-123", str(vars(client).get("model")))


@mock.patch.dict(os.environ, CLEAN_ENV, clear=True)
class GenerationTests(unittest.TestCase):
    def test_structured_json_request_configuration(self):
        client, sdk = make([response('{"name": "Glowfern"}')])
        result = client.generate_structured("prompt", Small, system_prompt="SYS")
        self.assertEqual(result.name, "Glowfern")
        config = sdk.calls[0].config
        self.assertEqual(sdk.calls[0].model, "gemini-3.5-flash-lite")
        self.assertEqual(config.response_mime_type, "application/json")
        self.assertEqual(config.response_json_schema,
                         transport_schema(Small.model_json_schema()))
        self.assertEqual(config.temperature, 0)
        self.assertTrue(config.system_instruction.startswith("SYS"))


class TransportSchemaTests(unittest.TestCase):
    """The simplified schema sent to Gemini (fix for HTTP 400 'too many states')."""

    def setUp(self):
        from app.agents.profiling_agent import FlatProfileExtraction, FocusedExtraction
        self.models = [FlatProfileExtraction, FocusedExtraction]

    @staticmethod
    def nodes(schema):
        """Yield every schema node (not property-name mappings)."""
        stack = [schema]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                yield node
                for key, value in node.items():
                    if key in ("properties", "$defs") and isinstance(value, dict):
                        stack.extend(value.values())
                    else:
                        stack.append(value)

    def test_drops_annotations_and_bounds(self):
        dropped = {"description", "title", "default", "minimum", "maximum"}
        for model in self.models:
            simplified = transport_schema(model.model_json_schema())
            for node in self.nodes(simplified):
                self.assertFalse(dropped & set(node), model.__name__)

    def test_structure_and_real_title_field_preserved(self):
        for model in self.models:
            full = model.model_json_schema()
            simplified = transport_schema(full)
            self.assertEqual(set(full.get("$defs", {})), set(simplified.get("$defs", {})))
            self.assertEqual(set(full["properties"]), set(simplified["properties"]))
            for name, definition in full.get("$defs", {}).items():
                self.assertEqual(set(definition.get("properties", {})),
                                 set(simplified["$defs"][name].get("properties", {})), name)
                self.assertEqual(definition.get("required"),
                                 simplified["$defs"][name].get("required"), name)
                self.assertEqual(definition.get("additionalProperties"),
                                 simplified["$defs"][name].get("additionalProperties"), name)
        flat = transport_schema(self.models[0].model_json_schema())["$defs"]["FlatClaim"]
        self.assertEqual(len(flat["properties"]["field"]["enum"]), 42)
        self.assertIn("identity.title", flat["properties"]["field"]["enum"])
        self.assertEqual(len(flat["properties"]["classification"]["enum"]), 4)
        claim = transport_schema(self.models[1].model_json_schema())["$defs"]["Claim"]
        self.assertEqual(len(claim["properties"]["classification"]["enum"]), 5)

    def test_flat_schema_complexity_stays_low(self):
        """Regression guard: the rejected nested schema had 56 refs / 27 anyOf."""
        text = json.dumps(transport_schema(self.models[0].model_json_schema()))
        self.assertLessEqual(text.count('"$ref"'), 10)
        self.assertLessEqual(text.count('"anyOf"'), 10)
        self.assertLess(len(text), 4000)

    def test_refs_still_resolve_and_input_not_mutated(self):
        full = self.models[0].model_json_schema()
        before = json.dumps(full, sort_keys=True)
        simplified = transport_schema(full)
        self.assertEqual(json.dumps(full, sort_keys=True), before)
        refs = re.findall(r'"\$ref": "#/\$defs/([^"]+)"', json.dumps(simplified))
        self.assertTrue(refs)
        self.assertTrue(set(refs) <= set(simplified["$defs"]))

    def test_schema_is_materially_smaller(self):
        full = json.dumps(self.models[0].model_json_schema())
        simplified = json.dumps(transport_schema(self.models[0].model_json_schema()))
        self.assertLess(len(simplified), len(full) * 0.8)
        full = json.dumps(self.models[1].model_json_schema())
        simplified = json.dumps(transport_schema(self.models[1].model_json_schema()))
        self.assertLess(len(simplified), len(full) * 0.6)

    def test_local_validation_still_enforces_dropped_bounds(self):
        from app.schemas.profile import Evidence, ReadinessProfile
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            Evidence.model_validate({"source_file": "a.pdf", "page": 0})
        with self.assertRaises(ValidationError):
            ReadinessProfile.model_validate({"reported_trl": 12})

    def test_one_corrective_retry_on_validation_error(self):
        client, sdk = make([response('{"wrong": 1}'), response('{"name": "ok"}')])
        self.assertEqual(client.generate_structured("p", Small).name, "ok")
        self.assertEqual(len(sdk.calls), 2)
        self.assertIn("failed schema validation", sdk.calls[1].contents[1])

    def test_invalid_output_never_accepted(self):
        client, _ = make([response("not json"), response('{"x": 1}')])
        with self.assertRaises(GeminiResponseError):
            client.generate_structured("p", Small)

    def test_truncated_output_rejected(self):
        client, _ = make([response('{"name": "x"}', finish="MAX_TOKENS")])
        with self.assertRaises(GeminiResponseError):
            client.generate_structured("p", Small)

    def test_429_is_quota_error_and_not_retried(self):
        client, sdk = make([FakeAPIError(429, "Quota exceeded per day"), response('{"name": "x"}')])
        with self.assertRaises(GeminiQuotaError):
            client.generate_structured("p", Small)
        self.assertEqual(len(sdk.calls), 1)
        self.assertEqual(client.remaining_requests_today(), 0)

    def test_errors_do_not_echo_sdk_details(self):
        client, _ = make([FakeAPIError(400, "CONFIDENTIAL DOC TEXT")])
        with self.assertRaises(GeminiError) as caught:
            client.generate_structured("p", Small)
        self.assertNotIn("CONFIDENTIAL", str(caught.exception))
        self.assertIn("HTTP 400", str(caught.exception))


@mock.patch.dict(os.environ, CLEAN_ENV, clear=True)
class UnavailableRetryTests(unittest.TestCase):
    """HTTP 503 gets exactly one delayed retry; nothing else is retried."""

    def make(self, outputs):
        self.sleeps = []
        return make(outputs, sleep=self.sleeps.append)

    def test_single_503_is_retried_once_and_succeeds(self):
        client, sdk = self.make([FakeAPIError(503, "overloaded"), response('{"name": "ok"}')])
        self.assertEqual(client.generate_structured("p", Small).name, "ok")
        self.assertEqual(len(sdk.calls), 2)
        self.assertEqual(self.sleeps, [15.0])
        # Both attempts count against the daily quota.
        self.assertEqual(client.remaining_requests_today(), 498)

    def test_second_503_fails_without_further_attempts(self):
        client, sdk = self.make([FakeAPIError(503, "overloaded"),
                                 FakeAPIError(503, "overloaded"),
                                 response('{"name": "never"}')])
        with self.assertRaises(GeminiError) as caught:
            client.generate_structured("p", Small)
        self.assertEqual(len(sdk.calls), 2)
        self.assertEqual(len(self.sleeps), 1)
        self.assertIn("after one retry", str(caught.exception))
        self.assertNotIsInstance(caught.exception, GeminiQuotaError)

    def test_other_errors_are_never_retried(self):
        for error in (FakeAPIError(429, "quota per day"), FakeAPIError(400, "bad schema"),
                      FakeAPIError(500, "internal"), ConnectionError("down")):
            client, sdk = self.make([error, response('{"name": "never"}')])
            with self.assertRaises(GeminiError):
                client.generate_structured("p", Small)
            self.assertEqual(len(sdk.calls), 1, repr(error))
            self.assertEqual(self.sleeps, [], repr(error))

    def test_retry_delay_configurable_and_bounded(self):
        for value, expected in (("0", 0.0), ("5", 5.0), ("600", 60.0), ("-3", 0.0)):
            with mock.patch.dict(os.environ, {"GEMINI_503_RETRY_DELAY_SECONDS": value}):
                client, _ = self.make([])
            self.assertEqual(client.unavailable_retry_delay, expected, value)

    def test_retry_respects_daily_limit(self):
        with mock.patch.dict(os.environ, {"GEMINI_RPD_LIMIT": "1"}):
            client, sdk = self.make([FakeAPIError(503, "overloaded"), response('{"name": "x"}')])
        with self.assertRaises(GeminiQuotaError):
            client.generate_structured("p", Small)
        self.assertEqual(len(sdk.calls), 1)


class RateLimiterTests(unittest.TestCase):
    def setUp(self):
        self.t = 0.0
        self.day = datetime(2026, 11, 24, 12, tzinfo=timezone(timedelta(hours=-8)))
        self.limiter = FreeTierRateLimiter(
            clock=lambda: self.t, sleep=self._sleep, now=lambda: self.day
        )

    def _sleep(self, seconds):
        self.t += seconds

    def test_rpm_waits_for_window(self):
        for _ in range(5):
            self.limiter.acquire("m", rpm=5, rpd=20, max_wait_seconds=65)
        self.assertEqual(self.t, 0.0)
        self.limiter.acquire("m", rpm=5, rpd=20, max_wait_seconds=65)
        self.assertGreaterEqual(self.t, 60.0)

    def test_rpm_refuses_if_wait_too_long(self):
        for _ in range(5):
            self.limiter.acquire("m", rpm=5, rpd=20, max_wait_seconds=0)
        with self.assertRaises(GeminiQuotaError):
            self.limiter.acquire("m", rpm=5, rpd=20, max_wait_seconds=0)

    def test_rpd_hard_stop_and_daily_reset(self):
        for _ in range(3):
            self.t += 61
            self.limiter.acquire("m", rpm=5, rpd=3, max_wait_seconds=0)
        with self.assertRaises(GeminiQuotaError):
            self.limiter.acquire("m", rpm=5, rpd=3, max_wait_seconds=0)
        self.assertEqual(self.limiter.remaining_today("m", 3), 0)
        self.day += timedelta(days=1)
        self.limiter.acquire("m", rpm=5, rpd=3, max_wait_seconds=0)
        self.assertEqual(self.limiter.remaining_today("m", 3), 2)

    def test_tpm_waits_when_token_window_full(self):
        self.limiter.acquire("m", rpm=5, rpd=20, max_wait_seconds=65,
                             tokens=150_000, tpm=250_000)
        self.limiter.acquire("m", rpm=5, rpd=20, max_wait_seconds=65,
                             tokens=150_000, tpm=250_000)
        self.assertGreaterEqual(self.t, 60.0)

    def test_single_request_over_tpm_rejected_without_counting(self):
        with self.assertRaises(GeminiQuotaError):
            self.limiter.acquire("m", rpm=5, rpd=20, max_wait_seconds=65,
                                 tokens=300_000, tpm=250_000)
        self.assertEqual(self.limiter.remaining_today("m", 20), 20)


@mock.patch.dict(os.environ, CLEAN_ENV, clear=True)
class TokenEstimateTests(unittest.TestCase):
    def test_estimate_includes_prompt_system_and_schema(self):
        client, sdk = make([response('{"name": "x"}')])
        client.generate_structured("x" * 35_000, Small, system_prompt="S" * 3_500)
        config = sdk.calls[0].config
        estimate = GeminiClient.estimate_tokens(sdk.calls[0].contents, config)
        self.assertGreater(estimate, 11_000)
        self.assertEqual(client.tpm, 250_000)


if __name__ == "__main__":
    unittest.main()
