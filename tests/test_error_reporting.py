"""Offline tests: generation failures are logged safely and reported specifically."""

import unittest
from unittest import mock

import _fixtures as fx  # noqa: F401  (adds backend to sys.path)
from fastapi.testclient import TestClient

import app.main
from app.core.account_status import ActiveAccount, get_account_status_service
from app.services.cloud_authorization import CloudProcessingNotAuthorized
from app.services.document_processor import DocumentProcessingError
from app.services.gemini_client import (
    GeminiConfigurationError,
    GeminiError,
    GeminiQuotaError,
    GeminiResponseError,
)

LOGGER = "app.api.profiles"
URL = f"/api/inventions/{fx.INVENTION_ID}/profile/generate"
UNCHANGED = "Your saved draft has not been changed."
FAKE_SECRETS = ("AIzaSyFAKEFAKEFAKEFAKEFAKEFAKEFAKE00", "AQ.FAKEfakeFAKEfake1234567890",
                "sb_secret_FAKEfake123456", "eyJhbGciOiJIUzI1NiJ9.FAKEPAYLOADFAKE.SIG")


class _ActiveAccountStatus:
    """Authentication mock: every token belongs to an active account."""

    async def verify_active(self, token):
        return ActiveAccount(user_id=fx.OWNER_ID, access_token=token)


class ErrorReportingTests(unittest.TestCase):
    def setUp(self):
        overrides = app.main.app.dependency_overrides
        overrides[get_account_status_service] = _ActiveAccountStatus
        self.addCleanup(overrides.pop, get_account_status_service, None)
        self.client = TestClient(app.main.app)

    def generate(self, error):
        service = mock.Mock()
        service.generate_draft = mock.AsyncMock(side_effect=error)
        with mock.patch("app.api.profiles.ProfileService", return_value=service):
            with self.assertLogs(LOGGER, level="WARNING") as logs:
                response = self.client.post(URL, headers={"Authorization": "Bearer fake"},
                                            json={"cloud_processing_consent": True})
        return response, "\n".join(logs.output)

    def test_double_503_reported_as_overloaded_and_logged(self):
        error = GeminiError("Gemini request failed (HTTP 503 UNAVAILABLE) after one retry. "
                            "The model is temporarily overloaded; try again later.")
        response, log = self.generate(error)
        self.assertEqual(response.status_code, 503)
        self.assertIn("temporarily overloaded (HTTP 503 after one retry)", response.json()["detail"])
        self.assertIn(UNCHANGED, response.json()["detail"])
        self.assertIn("failed (Gemini): GeminiError: Gemini request failed (HTTP 503", log)

    def test_other_gemini_errors_show_their_safe_message(self):
        cases = [GeminiResponseError("Gemini returned invalid structured data after 2 attempts. "
                                     "The response was not accepted."),
                 GeminiError("Gemini request failed (HTTP 400 INVALID_ARGUMENT)."),
                 GeminiResponseError("Gemini output reached its token limit. "
                                     "The incomplete result was rejected.")]
        for error in cases:
            response, log = self.generate(error)
            self.assertEqual(response.status_code, 502, error)
            detail = response.json()["detail"]
            self.assertIn(str(error).split(".")[0], detail)
            self.assertIn(UNCHANGED, detail)
            self.assertIn(type(error).__name__, log)

    def test_known_input_problem_is_422_with_reason(self):
        error = RuntimeError("No documents were confidently identified as relevant. "
                             "Review the uploaded documents before profiling.")
        response, log = self.generate(error)
        self.assertEqual(response.status_code, 422)
        self.assertIn("No documents were confidently identified as relevant", response.json()["detail"])
        self.assertIn("failed: RuntimeError: No documents were confidently", log)

    def test_unexpected_error_stays_generic_but_is_logged(self):
        response, log = self.generate(RuntimeError("internal detail xyz"))
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"],
                         "AI profile generation failed. Your saved draft has not been changed.")
        self.assertNotIn("internal detail xyz", response.text)
        self.assertIn("RuntimeError: internal detail xyz", log)

    def test_existing_mappings_unchanged_and_now_logged(self):
        for error, status in ((CloudProcessingNotAuthorized("AI profiling is not authorized."), 403),
                              (GeminiQuotaError("quota"), 429),
                              (GeminiConfigurationError("GEMINI_API_KEY is not configured."), 503),
                              (DocumentProcessingError("Database query failed (HTTP 500)."), 502)):
            response, log = self.generate(error)
            self.assertEqual(response.status_code, status, error)
            self.assertIn(type(error).__name__, log)
        self.assertEqual(response.json()["detail"], "Invention document processing failed.")

    def test_secret_like_strings_never_logged_or_returned(self):
        for error_class in (GeminiError, RuntimeError):
            error = error_class("Gemini request failed key=%s %s %s Bearer abc.def %s" % FAKE_SECRETS)
            response, log = self.generate(error)
            for secret in FAKE_SECRETS + ("abc.def",):
                self.assertNotIn(secret, log, error_class)
                self.assertNotIn(secret, response.text, error_class)
            self.assertIn("<redacted>", log)

    def test_log_is_a_single_line_without_traceback(self):
        _, log = self.generate(GeminiError("Gemini request failed (HTTP 400 INVALID_ARGUMENT).\nsecond line"))
        self.assertEqual(len(log.splitlines()), 1)
        self.assertNotIn("Traceback", log)


if __name__ == "__main__":
    unittest.main()
