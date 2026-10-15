import json
import time
from typing import Any

from labcatalog.exceptions import LLMError
from labcatalog.llm.base import CallMetadata, LLMClient, ToolSchema
from labcatalog.llm.retry import with_retries

# Local servers want some key in the header but do not check it.
LOCAL_KEY = "local"


class OpenAIClient(LLMClient):
    # With a base_url it talks to a local OpenAI-compatible server (Ollama, LM Studio, vLLM).
    def __init__(self, *, model: str, base_url: str | None = None, max_retries: int = 3) -> None:
        try:
            import openai
        except ImportError as e:
            raise LLMError("The openai package is missing: pip install labcatalog[ai]") from e
        self._openai = openai
        # with_retries is the one retry layer; the SDK's own retries would multiply its attempts.
        if base_url:
            self._client = openai.OpenAI(base_url=base_url, api_key=LOCAL_KEY, max_retries=0)
        else:
            try:
                self._client = openai.OpenAI(max_retries=0)
            except openai.OpenAIError as e:
                raise LLMError(f"OpenAI: {e}") from e
        self._provider = "local" if base_url else "openai"
        self._model = model
        self._max_retries = max_retries

    @property
    def provider_name(self) -> str:
        return self._provider

    @property
    def model_name(self) -> str:
        return self._model

    def complete_structured(
        self, *, system: str, user_message: str, tool_schema: ToolSchema
    ) -> tuple[dict[str, Any], CallMetadata]:
        openai = self._openai

        # A JSON schema response format, which local servers enforce for any model,
        # where tool calling depends on each model's template.
        def call():
            return self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": tool_schema.name,
                        "description": tool_schema.description,
                        "schema": tool_schema.input_schema,
                        "strict": True,
                    },
                },
            )

        def is_retryable(e: Exception) -> bool:
            if isinstance(
                e,
                openai.RateLimitError
                | openai.APITimeoutError
                | openai.APIConnectionError
                | openai.InternalServerError,
            ):
                return True
            return isinstance(e, openai.APIStatusError) and e.status_code >= 500

        name = "Local model" if self._provider == "local" else "OpenAI"
        t0 = time.monotonic()
        try:
            response = with_retries(call, is_retryable=is_retryable, max_retries=self._max_retries)
        except openai.AuthenticationError as e:
            raise LLMError(f"{name} authentication failed: {e}") from e
        except openai.BadRequestError as e:
            raise LLMError(f"{name} rejected the request: {e}") from e
        except Exception as e:
            raise LLMError(f"{name} call failed: {e}") from e
        latency_ms = int((time.monotonic() - t0) * 1000)

        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise LLMError(f"{name} cut the answer off before it was complete.")
        if choice.message.refusal:
            raise LLMError(f"{name} declined to answer: {choice.message.refusal}")
        try:
            output = json.loads(choice.message.content)
        except (ValueError, TypeError) as e:
            raise LLMError(f"{name} did not return valid JSON: {e}") from e

        usage = response.usage
        meta = CallMetadata(
            provider=self._provider,
            model=self._model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=latency_ms,
        )
        return output, meta
