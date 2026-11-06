import json
import os
import time
from collections.abc import Sequence
from typing import Any

from labcatalog.exceptions import LLMError
from labcatalog.llm.base import CallMetadata, Image, LLMClient, ToolSchema
from labcatalog.llm.retry import with_retries

KEY_ENV = "GEMINI_API_KEY"
MAX_TOKENS = 16000


class GeminiClient(LLMClient):
    # The Google Gen AI SDK, with the schema as a structured output (response_json_schema).
    def __init__(self, *, model: str, max_retries: int = 3) -> None:
        try:
            from google import genai
            from google.genai import errors, types
        except ImportError as e:
            raise LLMError("The google-genai package is missing: pip install labcatalog[ai]") from e
        self._errors, self._types = errors, types
        try:
            self._client = genai.Client(api_key=os.environ.get(KEY_ENV))
        except ValueError as e:
            raise LLMError(f"Gemini: {e}") from e
        self._model = model
        self._max_retries = max_retries

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    def complete_structured(
        self,
        *,
        system: str,
        user_message: str,
        tool_schema: ToolSchema,
        images: Sequence[Image] = (),
    ) -> tuple[dict[str, Any], CallMetadata]:
        errors, types = self._errors, self._types
        contents = [
            *(
                types.Part.from_bytes(data=image.data, mime_type=image.media_type)
                for image in images
            ),
            user_message,
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=MAX_TOKENS,
            response_mime_type="application/json",
            response_json_schema=tool_schema.input_schema,
        )

        def call():
            return self._client.models.generate_content(
                model=self._model, contents=contents, config=config
            )

        def is_retryable(e: Exception) -> bool:
            return isinstance(e, errors.APIError) and (e.code in (408, 429) or e.code >= 500)

        t0 = time.monotonic()
        try:
            response = with_retries(call, is_retryable=is_retryable, max_retries=self._max_retries)
        except errors.ClientError as e:
            raise LLMError(f"Gemini rejected the request: {e}") from e
        except Exception as e:
            raise LLMError(f"Gemini call failed: {e}") from e
        latency_ms = int((time.monotonic() - t0) * 1000)

        candidate = response.candidates[0] if response.candidates else None
        reason = getattr(getattr(candidate, "finish_reason", None), "name", "")
        if reason == "MAX_TOKENS":
            raise LLMError(f"The answer was cut off at {MAX_TOKENS} tokens.")
        if candidate is None or reason in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"):
            raise LLMError(f"Gemini declined to answer ({reason or 'no answer'}).")
        try:
            output = json.loads(response.text)
        except (ValueError, TypeError) as e:
            raise LLMError(f"Gemini did not return valid JSON: {e}") from e

        usage = response.usage_metadata
        meta = CallMetadata(
            provider="gemini",
            model=self._model,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            # Thinking models count their reasoning apart from the answer.
            output_tokens=(getattr(usage, "candidates_token_count", 0) or 0)
            + (getattr(usage, "thoughts_token_count", 0) or 0),
            latency_ms=latency_ms,
        )
        return output, meta
