import os
import time
from typing import Any

from labcatalog.exceptions import LLMError
from labcatalog.llm.base import CallMetadata, LLMClient, ToolSchema
from labcatalog.llm.retry import with_retries

KEY_ENV = "GEMINI_API_KEY"
# Errors that fail the same way on every attempt, such as a wrong key or a rejected schema.
PERMANENT_MARKERS = (
    "api key",
    "api_key",
    "unauthenticated",
    "permission",
    "invalid argument",
    "invalid_argument",
    "bad request",
)


def is_retryable(e: Exception) -> bool:
    # google-generativeai has no stable exception classes, so this reads the status or the message.
    code = getattr(e, "code", None)
    if isinstance(code, int):
        return code in (408, 429) or code >= 500
    message = str(e).lower()
    return not any(marker in message for marker in PERMANENT_MARKERS)


def plain(obj: Any) -> Any:
    # Gemini returns proto maps and lists; the rest of labcatalog wants plain Python.
    if obj is None or isinstance(obj, str | bytes | bool | int | float):
        return obj
    if hasattr(obj, "items"):
        return {k: plain(v) for k, v in obj.items()}
    if hasattr(obj, "__iter__"):
        return [plain(v) for v in obj]
    return obj


class GeminiClient(LLMClient):
    # Untested against a live key, as in the package it was ported from.
    def __init__(self, *, model: str, max_retries: int = 3) -> None:
        try:
            import google.generativeai as genai
        except ImportError as e:
            raise LLMError(
                "The google-generativeai package is missing: pip install labcatalog[ai]"
            ) from e
        self._genai = genai
        genai.configure(api_key=os.environ.get(KEY_ENV))
        self._model = model
        self._max_retries = max_retries

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    def complete_structured(
        self, *, system: str, user_message: str, tool_schema: ToolSchema
    ) -> tuple[dict[str, Any], CallMetadata]:
        tool = {
            "function_declarations": [
                {
                    "name": tool_schema.name,
                    "description": tool_schema.description,
                    # Gemini's schema has no additionalProperties field.
                    "parameters": {
                        k: v
                        for k, v in tool_schema.input_schema.items()
                        if k != "additionalProperties"
                    },
                }
            ]
        }
        model = self._genai.GenerativeModel(self._model, system_instruction=system, tools=[tool])

        def call():
            return model.generate_content(
                user_message,
                tool_config={
                    "function_calling_config": {
                        "mode": "ANY",
                        "allowed_function_names": [tool_schema.name],
                    }
                },
            )

        t0 = time.monotonic()
        try:
            response = with_retries(call, is_retryable=is_retryable, max_retries=self._max_retries)
        except Exception as e:
            raise LLMError(f"Gemini call failed: {e}") from e
        latency_ms = int((time.monotonic() - t0) * 1000)

        output = None
        for part in response.candidates[0].content.parts:
            found = getattr(part, "function_call", None)
            if found is not None and found.name == tool_schema.name:
                output = plain(found.args)
                break
        if output is None:
            raise LLMError(f"Gemini did not call {tool_schema.name}.")

        usage = response.usage_metadata
        meta = CallMetadata(
            provider="gemini",
            model=self._model,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            latency_ms=latency_ms,
        )
        return dict(output), meta
