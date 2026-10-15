import json
import time
from typing import Any

from labcatalog.exceptions import LLMError
from labcatalog.llm.base import CallMetadata, LLMClient, ToolSchema
from labcatalog.llm.retry import with_retries

MAX_TOKENS = 16000


class AnthropicClient(LLMClient):
    def __init__(self, *, model: str, max_retries: int = 3) -> None:
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("The anthropic package is missing: pip install labcatalog[ai]") from e
        self._anthropic = anthropic
        # with_retries is the one retry layer; the SDK's own retries would multiply its attempts.
        self._client = anthropic.Anthropic(max_retries=0)
        self._model = model
        self._max_retries = max_retries

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model

    def complete_structured(
        self, *, system: str, user_message: str, tool_schema: ToolSchema
    ) -> tuple[dict[str, Any], CallMetadata]:
        anthropic = self._anthropic

        # Current models reject forced tool calls, so the schema goes in as a structured output.
        def call():
            return self._client.messages.create(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user_message}],
                output_config={
                    "format": {"type": "json_schema", "schema": tool_schema.input_schema}
                },
            )

        def is_retryable(e: Exception) -> bool:
            if isinstance(
                e,
                anthropic.RateLimitError | anthropic.APITimeoutError | anthropic.APIConnectionError,
            ):
                return True
            return isinstance(e, anthropic.APIStatusError) and e.status_code >= 500

        t0 = time.monotonic()
        try:
            response = with_retries(call, is_retryable=is_retryable, max_retries=self._max_retries)
        except anthropic.AuthenticationError as e:
            raise LLMError(f"Anthropic authentication failed: {e}") from e
        except anthropic.BadRequestError as e:
            raise LLMError(f"Anthropic rejected the request: {e}") from e
        except Exception as e:
            raise LLMError(f"Anthropic call failed: {e}") from e
        latency_ms = int((time.monotonic() - t0) * 1000)

        if response.stop_reason == "refusal":
            details = response.stop_details
            reason = details.explanation if details is not None else ""
            raise LLMError(f"The model declined to answer. {reason}".strip())
        if response.stop_reason == "max_tokens":
            raise LLMError(f"The answer was cut off at {MAX_TOKENS} tokens.")
        text = next(b.text for b in response.content if b.type == "text")

        usage = response.usage
        meta = CallMetadata(
            provider="anthropic",
            model=self._model,
            # Anthropic counts cache reads and writes apart from input_tokens.
            input_tokens=(usage.input_tokens or 0)
            + (usage.cache_read_input_tokens or 0)
            + (usage.cache_creation_input_tokens or 0),
            output_tokens=usage.output_tokens or 0,
            latency_ms=latency_ms,
        )
        return json.loads(text), meta
