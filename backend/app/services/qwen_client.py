
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError


# Load the existing project .env file.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")


class QwenClient:
    def __init__(self):
        self.model = os.getenv(
            "QWEN_MODEL", "qwen3.5:9b"
        )

        self.base_url = os.getenv(
            "QWEN_BASE_URL",
            "http://localhost:11434"
        ).rstrip("/")

        # Keep confidential invention data on the
        # local machine. Do not use external AI APIs.
        parsed = urlparse(self.base_url)

        if (
            parsed.scheme != "http"
            or parsed.hostname not in (
                "localhost",
                "127.0.0.1",
                "::1"
            )
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
        ):
            raise ValueError(
                "Qwen must use a local Ollama endpoint."
            )

    def check_connection(self):
        """Check Ollama connectivity and installed models."""

        try:
            response = httpx.get(
                f"{self.base_url}/api/tags",
                timeout=10.0
            )

            response.raise_for_status()

            models = [
                item["name"]
                for item in response.json().get(
                    "models", []
                )
            ]

            return {
                "connected": True,
                "model": self.model,
                "model_installed": self.model in models,
                "available_models": models
            }

        except httpx.HTTPError as error:
            return {
                "connected": False,
                "error": str(error)
            }

    @staticmethod
    def format_validation_errors(
        error: ValidationError
    ) -> str:
        """
        Extract safe validation feedback.

        Do not include confidential input values,
        document text, or full generated responses.
        """

        details = error.errors(
            include_input=False,
            include_url=False
        )

        messages = []

        for item in details[:20]:
            location = ".".join(
                str(part)
                for part in item.get("loc", [])
            )

            reason = item.get(
                "msg", "Invalid field value."
            )

            messages.append(
                f"- {location}: {reason}"
            )

        if len(details) > 20:
            messages.append(
                f"- {len(details) - 20} additional "
                "validation errors."
            )

        return "\n".join(messages)

    def generate_structured(
        self,
        prompt: str,
        response_model: type[BaseModel],
        system_prompt: str = (
            "You are an invention profiling assistant. "
            "Extract only information supported by the input. "
            "Do not invent missing information."
        ),
        num_predict: int = 6144,
        num_ctx: int = 24576,
        timeout_seconds: float = 900.0,
        max_retries: int = 2
    ) -> BaseModel:
        """
        Generate validated structured JSON with local Qwen.

        If Pydantic validation fails, retry with
        specific validation feedback.

        Maximum attempts = 1 + max_retries.

        Invalid results are never automatically accepted.
        """

        # -----------------------------------------
        # Input validation
        # -----------------------------------------

        if (
            not isinstance(prompt, str)
            or not prompt.strip()
        ):
            raise ValueError(
                "A non-empty prompt is required."
            )

        if (
            not isinstance(response_model, type)
            or not issubclass(
                response_model, BaseModel
            )
        ):
            raise TypeError(
                "response_model must inherit from BaseModel."
            )

        if not 128 <= num_predict <= 8192:
            raise ValueError(
                "num_predict must be between 128 and 8192."
            )

        if not 4096 <= num_ctx <= 32768:
            raise ValueError(
                "num_ctx must be between 4096 and 32768."
            )

        if timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be positive."
            )

        if (
            not isinstance(max_retries, int)
            or not 0 <= max_retries <= 3
        ):
            raise ValueError(
                "max_retries must be between 0 and 3."
            )

        # -----------------------------------------
        # Structured output instructions
        # -----------------------------------------

        schema_instructions = """
STRUCTURED JSON REQUIREMENTS:

Follow the provided JSON schema exactly.

For every Claim object:
- Always include the classification field.
- Allowed classifications:
  document_fact, registration_fact,
  inference, recommendation, missing.

Rules:
1. If classification is missing, value MUST be null.
2. Never use missing with a non-null value.
3. A non-missing claim must have a non-empty value.
4. document_fact requires supporting source evidence.
5. Use exact document filenames and verbatim excerpts.
6. Do not invent document citations or page numbers.
7. registration_fact must reflect supplied registration data.
8. inference is an interpretation, not a verified fact.
9. recommendation is a proposed action, not a verified fact.
10. Omit optional unsupported claims or use
    classification=missing and value=null.

Do not change the factual meaning of the source material
merely to satisfy the schema.
Return only valid JSON.
"""

        complete_system_prompt = (
            system_prompt.strip()
            + "\n\n"
            + schema_instructions
        )

        # -----------------------------------------
        # Ollama request configuration
        # -----------------------------------------

        base_messages = [
            {
                "role": "system",
                "content": complete_system_prompt
            },
            {
                "role": "user",
                "content": prompt
            }
        ]

        payload = {
            "model": self.model,
            "messages": base_messages,
            "stream": False,
            "think": False,
            "format": response_model.model_json_schema(),
            "options": {
                "temperature": 0,
                "num_predict": num_predict,
                "num_ctx": num_ctx
            },
            "keep_alive": "5m"
        }

        validation_feedback = None

        # -----------------------------------------
        # Request and validation retry
        # -----------------------------------------

        try:
            with httpx.Client(
                timeout=httpx.Timeout(
                    timeout_seconds,
                    connect=10.0
                )
            ) as client:

                for attempt in range(max_retries + 1):

                    messages = list(base_messages)

                    if validation_feedback is not None:
                        messages.append({
                            "role": "user",
                            "content": (
                                "Your previous JSON response "
                                "failed schema validation.\n\n"
                                "Validation errors:\n"
                                f"{validation_feedback}\n\n"
                                "Generate a complete corrected "
                                "JSON response from the original "
                                "source information.\n"
                                "Explicitly classify every Claim. "
                                "Never use classification=missing "
                                "with a non-null value.\n"
                                "Never manufacture evidence, "
                                "claims, or citations to fix errors.\n"
                                "Return only schema-valid JSON."
                            )
                        })

                    payload["messages"] = messages

                    response = client.post(
                        f"{self.base_url}/api/chat",
                        json=payload
                    )

                    response.raise_for_status()

                    result = response.json()

                    content = (
                        result.get("message", {})
                        .get("content", "")
                    )

                    if not isinstance(content, str):
                        raise RuntimeError(
                            "Qwen returned an unexpected response."
                        )

                    if not content.strip():
                        raise RuntimeError(
                            "Qwen returned an empty response."
                        )

                    if result.get("done_reason") == "length":
                        raise RuntimeError(
                            "Qwen output reached its token limit. "
                            "The incomplete result was rejected."
                        )

                    # Validate output against Pydantic.
                    try:
                        validated = (
                            response_model.model_validate_json(
                                content
                            )
                        )

                        return validated

                    except ValidationError as error:

                        # No more retries available.
                        if attempt >= max_retries:
                            raise RuntimeError(
                                "Qwen returned invalid structured "
                                "data after "
                                f"{max_retries + 1} attempts. "
                                "The response was not accepted."
                            ) from error

                        # Give Qwen the exact failed fields
                        # without exposing raw document content.
                        validation_feedback = (
                            self.format_validation_errors(
                                error
                            )
                        )

            raise RuntimeError(
                "Qwen generation ended unexpectedly."
            )

        except httpx.HTTPError as error:
            raise RuntimeError(
                f"Local Ollama request failed: {error}"
            ) from error

        except ValueError as error:
            raise RuntimeError(
                "Qwen returned invalid JSON or an "
                "unexpected response structure."
            ) from error
