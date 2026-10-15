from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolSchema:
    # A JSON Schema output contract; each provider translates it to its own format.
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class CallMetadata:
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


class LLMClient(ABC):
    # Providers must enforce the schema at the API, never parse free-text JSON.
    @abstractmethod
    def complete_structured(
        self, *, system: str, user_message: str, tool_schema: ToolSchema
    ) -> tuple[dict[str, Any], CallMetadata]: ...

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...
