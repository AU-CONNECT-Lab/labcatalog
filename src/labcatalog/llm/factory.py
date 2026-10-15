from labcatalog.exceptions import LLMError
from labcatalog.llm.base import LLMClient

PROVIDERS = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "gemini": "Gemini",
    "local": "Local (OpenAI-compatible server)",
}
# Keys come only from the environment; labcatalog never stores them.
KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}


def make_llm_client(provider: str, model: str, base_url: str = "") -> LLMClient:
    # No default model: names date fast, and a stale default is worse than being asked.
    if not model.strip():
        raise LLMError("No model set. Enter one on the Settings page.")
    if provider == "anthropic":
        from labcatalog.llm.providers.anthropic import AnthropicClient

        return AnthropicClient(model=model)
    if provider == "openai":
        from labcatalog.llm.providers.openai import OpenAIClient

        return OpenAIClient(model=model)
    if provider == "local":
        if not base_url.strip():
            raise LLMError("No address set for the local model server. Enter it on Settings.")
        from labcatalog.llm.providers.openai import OpenAIClient

        return OpenAIClient(model=model, base_url=base_url.strip())
    if provider == "gemini":
        from labcatalog.llm.providers.gemini import GeminiClient

        return GeminiClient(model=model)
    raise LLMError(f"Unknown model provider {provider!r}; choose one on the Settings page.")
