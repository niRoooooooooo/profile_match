"""Server-side Gemini client for structured invention profiling.

Uses the official google-genai SDK with JSON-schema structured output.
Credentials are read from the server environment only and are never logged,
returned, or included in error messages. One project key is shared by all
Gemini-powered agents; quotas are per model, per Google Cloud project.

PRIVACY: Free-tier Gemini requests may be used by Google to improve its
products. This client refuses any invention not registered as public; the
caller must ALSO pass app.services.cloud_authorization, which requires an
explicit server-side approval for each invention.
"""

import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")


# Approved primary Profiling Agent model after the fictional Glowfern tests
# (2026-11-24). Hydrogen remains selectable via GEMINI_MODEL, but is never
# invoked automatically (no fallback between models).
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"


@dataclass(frozen=True)
class FreeTierModel:
    rpm: int
    rpd: int
    tpm: int
    # Only models whose profiling accuracy has been accepted may be used for
    # real profile generation. Others are available for offline comparison.
    approved_for_profiling: bool


# Free-tier models only. Paid-only models are deliberately not listed, so
# they cannot be selected through configuration.
FREE_TIER_MODELS: dict[str, FreeTierModel] = {
    # Gemini 3.8 Flash and Gemini Embedding 2 are added only when the agents
    # that use them are approved and implemented.
    "gemini-4-hydrogen": FreeTierModel(
        rpm=5, rpd=20, tpm=250_000, approved_for_profiling=True
    ),
    "gemini-3.5-flash-lite": FreeTierModel(
        rpm=15, rpd=500, tpm=250_000, approved_for_profiling=True
    ),
}


class GeminiError(RuntimeError):
    """Base error. Messages never contain credentials or document text."""


class GeminiConfigurationError(GeminiError):
    pass


class GeminiPrivacyError(GeminiError):
    pass


class GeminiQuotaError(GeminiError):
    pass


class GeminiResponseError(GeminiError):
    pass


class _UnavailableError(Exception):
    """Internal marker for HTTP 503; never escapes GeminiClient._call."""


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as error:
        raise GeminiConfigurationError(f"{name} must be an integer.") from error


# Free-tier daily quotas reset at midnight Pacific time. tzdata is not
# guaranteed on Windows, so use UTC-8. During daylight time this resets one
# hour after Google does, which is the safe direction.
_QUOTA_DAY_TZ = timezone(timedelta(hours=-8))


class FreeTierRateLimiter:
    """Process-local, thread-safe RPM / TPM / RPD guard for each model.

    Counters live in memory: a server restart resets the local count, but
    Google still enforces the real quota. HTTP 429 responses are reported as
    quota errors and are never retried automatically.
    """

    def __init__(self, clock=time.monotonic, sleep=time.sleep, now=None):
        self._lock = threading.Lock()
        self._clock = clock
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(_QUOTA_DAY_TZ))
        self._minute: dict[str, deque] = {}
        self._day: dict[str, tuple[str, int]] = {}
        self._exhausted_day: dict[str, str] = {}

    def _today(self) -> str:
        return self._now().astimezone(_QUOTA_DAY_TZ).date().isoformat()

    def used_today(self, model: str) -> int:
        with self._lock:
            day, count = self._day.get(model, (self._today(), 0))
            return count if day == self._today() else 0

    def remaining_today(self, model: str, rpd: int) -> int:
        with self._lock:
            today = self._today()
            if self._exhausted_day.get(model) == today:
                return 0
            day, count = self._day.get(model, (today, 0))
            return max(0, rpd - (count if day == today else 0))

    def mark_exhausted(self, model: str):
        with self._lock:
            self._exhausted_day[model] = self._today()

    def acquire(
        self,
        model: str,
        rpm: int,
        rpd: int,
        max_wait_seconds: float,
        tokens: int = 0,
        tpm: int | None = None,
    ):
        """Reserve one request, waiting briefly for the per-minute window.

        ``tokens`` is a conservative local estimate of input tokens; it is
        checked against ``tpm`` over a rolling 60-second window.
        """
        if tpm is not None and tokens > tpm:
            raise GeminiQuotaError(
                f"This request (~{tokens} tokens) exceeds the free-tier "
                f"limit of {tpm} tokens per minute for {model}. Reduce the "
                "document size or GEMINI_MAX_CONTEXT_CHARACTERS."
            )
        deadline = self._clock() + max_wait_seconds
        while True:
            with self._lock:
                today = self._today()
                if self._exhausted_day.get(model) == today:
                    raise GeminiQuotaError(
                        f"Daily free-tier quota for {model} is exhausted."
                    )
                day, count = self._day.get(model, (today, 0))
                if day != today:
                    count = 0
                if count >= rpd:
                    raise GeminiQuotaError(
                        f"Daily free-tier limit ({rpd} requests) for "
                        f"{model} has been reached."
                    )

                window = self._minute.setdefault(model, deque())
                current = self._clock()
                while window and current - window[0][0] >= 60.0:
                    window.popleft()
                used_tokens = sum(item[1] for item in window)
                tokens_ok = tpm is None or used_tokens + tokens <= tpm
                if len(window) < rpm and tokens_ok:
                    window.append((current, tokens))
                    self._day[model] = (today, count + 1)
                    return
                wait = 60.0 - (current - window[0][0]) + 0.05

            if self._clock() + wait > deadline:
                raise GeminiQuotaError(
                    f"Per-minute free-tier limit ({rpm} requests / "
                    f"{tpm or 'n/a'} tokens) for {model} is busy. "
                    "Try again shortly."
                )
            self._sleep(wait)


# One shared limiter for the whole backend process.
RATE_LIMITER = FreeTierRateLimiter()


def _safe_validation_feedback(error: ValidationError) -> str:
    """Field locations and reasons only; never input values."""
    details = error.errors(include_input=False, include_url=False)
    lines = []
    for item in details[:20]:
        location = ".".join(str(part) for part in item.get("loc", []))
        lines.append(f"- {location}: {item.get('msg', 'Invalid field value.')}")
    if len(details) > 20:
        lines.append(f"- {len(details) - 20} additional validation errors.")
    return "\n".join(lines)


# Annotation keywords that only add constraint states for Gemini's
# constrained decoding ("schema produces a constraint that has too many
# states"). They are removed from the copy SENT to Gemini only; every
# response is still validated locally against the full Pydantic model, so
# bounds such as page >= 1 and TRL 1-9 are still enforced.
_TRANSPORT_DROP_KEYWORDS = frozenset({
    "description", "title", "default", "examples",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
})
# Keywords whose values map NAMES to sub-schemas; the names themselves
# (e.g. the profile's real "title" field) must never be removed.
_NAME_MAPPING_KEYWORDS = frozenset({"properties", "$defs", "definitions", "patternProperties"})


def transport_schema(schema):
    """Return a simplified copy of a JSON schema for Gemini structured output.

    Structure, property names, types, enums, required lists, references and
    additionalProperties are preserved; only annotations and numeric bounds
    are dropped. The input schema is not modified.
    """
    if isinstance(schema, list):
        return [transport_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    simplified = {}
    for keyword, value in schema.items():
        if keyword in _TRANSPORT_DROP_KEYWORDS:
            continue
        if keyword in _NAME_MAPPING_KEYWORDS and isinstance(value, dict):
            simplified[keyword] = {
                name: transport_schema(sub_schema) for name, sub_schema in value.items()
            }
        else:
            simplified[keyword] = transport_schema(value)
    return simplified


SCHEMA_INSTRUCTIONS = """
STRUCTURED JSON REQUIREMENTS:
Follow the provided JSON schema exactly.
For every Claim object:
- Always include classification: document_fact, registration_fact,
  inference, recommendation or missing.
- missing => value MUST be null. Never use missing with a non-null value.
- A non-missing claim must have a non-empty value.
- document_fact requires evidence with the exact source filename and a
  short VERBATIM excerpt copied character-for-character from the source.
- Do not invent citations, page numbers, sections or quotes.
- registration_fact must reflect supplied registration data.
- inference is an interpretation; recommendation is a proposed action.
Return only valid JSON.
"""


class GeminiClient:
    """Structured-output Gemini client using the official google-genai SDK."""

    provider = "gemini"

    def __init__(
        self,
        *,
        confidentiality: str | None,
        model: str | None = None,
        api_key: str | None = None,
        sdk_client=None,
        rate_limiter: FreeTierRateLimiter | None = None,
        require_profiling_approval: bool = True,
        sleep=time.sleep,
    ):
        # Defence in depth: the provider selector also enforces this.
        if (confidentiality or "").strip().lower() != "public":
            raise GeminiPrivacyError(
                "Gemini may only process inventions registered as public. "
                "Restricted or confidential inventions are blocked."
            )

        self.model = (model or os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()
        limits = FREE_TIER_MODELS.get(self.model)
        if limits is None:
            raise GeminiConfigurationError(
                f"Model '{self.model}' is not an allowed free-tier model. "
                f"Allowed: {', '.join(sorted(FREE_TIER_MODELS))}."
            )
        if (
            require_profiling_approval
            and not limits.approved_for_profiling
            and not _env_bool("GEMINI_FLASH_LITE_APPROVED")
        ):
            raise GeminiConfigurationError(
                f"Model '{self.model}' has not been approved for profiling. "
                "Compare it first, then set GEMINI_FLASH_LITE_APPROVED=true."
            )

        # Optional overrides may only LOWER the free-tier limits.
        self.rpm = min(limits.rpm, _env_int("GEMINI_RPM_LIMIT", limits.rpm))
        self.rpd = min(limits.rpd, _env_int("GEMINI_RPD_LIMIT", limits.rpd))
        self.tpm = min(limits.tpm, _env_int("GEMINI_TPM_LIMIT", limits.tpm))
        if self.rpm < 1 or self.rpd < 1:
            raise GeminiConfigurationError("Gemini rate limits must be positive.")

        self.max_output_tokens = _env_int("GEMINI_MAX_OUTPUT_TOKENS", 32768)
        self.timeout_ms = _env_int("GEMINI_TIMEOUT_SECONDS", 300) * 1000
        self.max_wait_seconds = float(_env_int("GEMINI_MAX_RPM_WAIT_SECONDS", 65))
        self.rate_limiter = rate_limiter or RATE_LIMITER
        # One delayed retry for HTTP 503 (model temporarily overloaded) only.
        self.unavailable_retry_delay = float(
            min(60, max(0, _env_int("GEMINI_503_RETRY_DELAY_SECONDS", 15)))
        )
        self._sleep = sleep

        if sdk_client is not None:
            self._client = sdk_client
        else:
            key = api_key or os.getenv("GEMINI_API_KEY")
            if not key or not key.strip():
                raise GeminiConfigurationError(
                    "GEMINI_API_KEY is not configured on the server."
                )
            self._client = self._build_sdk_client(key.strip())

    def __repr__(self) -> str:  # never expose the key
        return f"GeminiClient(model={self.model!r})"

    def _build_sdk_client(self, api_key: str):
        try:
            from google import genai
            from google.genai import types
        except ImportError as error:
            raise GeminiConfigurationError(
                "The google-genai package is not installed."
            ) from error
        return genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=self.timeout_ms,
                # Disable SDK auto-retries; each retry would consume quota.
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    def remaining_requests_today(self) -> int:
        return self.rate_limiter.remaining_today(self.model, self.rpd)

    def _config(self, system_prompt: str, response_model: type[BaseModel], max_tokens: int):
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            # Simplified copy for Gemini; full validation happens locally.
            response_json_schema=transport_schema(response_model.model_json_schema()),
            temperature=0,
            max_output_tokens=max_tokens,
        )

    @staticmethod
    def estimate_tokens(contents, config) -> int:
        """Conservative local estimate (~3.5 characters per token).

        Avoids a separate count_tokens API call. Includes the system prompt
        and the response schema, which are also sent with every request.
        """
        characters = sum(len(str(part)) for part in contents)
        characters += len(str(getattr(config, "system_instruction", "") or ""))
        characters += len(str(getattr(config, "response_json_schema", "") or ""))
        return int(characters / 3.5) + 1

    def _call(self, contents, config):
        """Send one request; on HTTP 503 only, wait and retry exactly once.

        Every attempt is counted by the rate limiter. All other errors
        (429 quota, 400 invalid request, auth, transport) fail immediately.
        """
        for attempt in (1, 2):
            try:
                return self._send(contents, config)
            except _UnavailableError as error:
                if attempt == 2:
                    raise GeminiError(
                        "Gemini request failed (HTTP 503 UNAVAILABLE) after one "
                        "retry. The model is temporarily overloaded; try again later."
                    ) from error.__cause__
                self._sleep(self.unavailable_retry_delay)
        raise GeminiError("Gemini request ended unexpectedly.")  # pragma: no cover

    def _send(self, contents, config):
        self.rate_limiter.acquire(
            self.model, self.rpm, self.rpd, self.max_wait_seconds,
            tokens=self.estimate_tokens(contents, config), tpm=self.tpm,
        )
        try:
            return self._client.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except GeminiError:
            raise
        except Exception as error:  # SDK / transport errors
            code = getattr(error, "code", None)
            status = getattr(error, "status", None)
            if code == 503:
                raise _UnavailableError() from error
            if code == 429:
                message = str(getattr(error, "message", "") or "").lower()
                if "day" in message or "daily" in message or "perday" in message:
                    self.rate_limiter.mark_exhausted(self.model)
                raise GeminiQuotaError(
                    f"Gemini free-tier quota exceeded for {self.model} (HTTP 429)."
                ) from error
            # Report only the code/status; SDK error details may echo input.
            detail = f"HTTP {code} {status}" if code else type(error).__name__
            raise GeminiError(f"Gemini request failed ({detail}).") from error

    @staticmethod
    def _response_text(response) -> str:
        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise GeminiResponseError("Gemini blocked the request.")

        candidates = getattr(response, "candidates", None) or []
        if candidates:
            reason = getattr(candidates[0], "finish_reason", None)
            reason_name = getattr(reason, "name", None) or (str(reason) if reason else None)
            if reason_name and reason_name.endswith("MAX_TOKENS"):
                raise GeminiResponseError(
                    "Gemini output reached its token limit. "
                    "The incomplete result was rejected."
                )
            if reason_name and not reason_name.endswith(("STOP", "FINISH_REASON_UNSPECIFIED")):
                raise GeminiResponseError(
                    f"Gemini did not complete the response ({reason_name})."
                )

        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise GeminiResponseError("Gemini returned an empty response.")
        return text

    def generate_structured(
        self,
        prompt: str,
        response_model: type[BaseModel],
        system_prompt: str = (
            "You are an invention profiling assistant. "
            "Extract only information supported by the input."
        ),
        num_predict: int = 6144,
        max_retries: int = 1,
        **_ignored,
    ) -> BaseModel:
        """Generate and Pydantic-validate one structured response.

        ``num_predict`` is a per-call output budget; at least the configured
        ``GEMINI_MAX_OUTPUT_TOKENS`` is allowed. A validation failure gets at
        most ``max_retries`` corrective attempts (each one counts against
        quota). Invalid output is never accepted.
        """
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("A non-empty prompt is required.")
        if not isinstance(response_model, type) or not issubclass(response_model, BaseModel):
            raise TypeError("response_model must inherit from BaseModel.")
        if not isinstance(max_retries, int) or not 0 <= max_retries <= 2:
            raise ValueError("max_retries must be between 0 and 2.")

        config = self._config(
            system_prompt.strip() + "\n\n" + SCHEMA_INSTRUCTIONS,
            response_model,
            max(int(num_predict), self.max_output_tokens),
        )
        feedback = None
        for attempt in range(max_retries + 1):
            contents = [prompt]
            if feedback is not None:
                contents.append(
                    "Your previous JSON response failed schema validation.\n"
                    f"Validation errors:\n{feedback}\n"
                    "Generate a complete corrected JSON response from the "
                    "original source information. Never manufacture evidence "
                    "or citations to fix errors. Return only schema-valid JSON."
                )
            text = self._response_text(self._call(contents, config))
            try:
                return response_model.model_validate_json(text)
            except ValidationError as error:
                if attempt >= max_retries:
                    raise GeminiResponseError(
                        "Gemini returned invalid structured data after "
                        f"{max_retries + 1} attempts. The response was not accepted."
                    ) from error
                feedback = _safe_validation_feedback(error)
        raise GeminiResponseError("Gemini generation ended unexpectedly.")
