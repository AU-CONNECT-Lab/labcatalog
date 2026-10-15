import json
from types import SimpleNamespace

import pytest

from labcatalog.exceptions import LLMError
from labcatalog.llm import ToolSchema, make_llm_client

SCHEMA = ToolSchema(
    "answer",
    "An answer.",
    {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    },
)


def test_the_factory_asks_for_a_model_and_a_local_address():
    with pytest.raises(LLMError, match="No model set"):
        make_llm_client("anthropic", " ")
    with pytest.raises(LLMError, match="No address set"):
        make_llm_client("local", "qwen2.5")
    with pytest.raises(LLMError, match="Unknown model provider"):
        make_llm_client("nobody", "x")


def test_anthropic_asks_for_a_structured_output_without_forcing_a_tool(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    client = make_llm_client("anthropic", "claude-test")
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            stop_details=None,
            content=[SimpleNamespace(type="text", text=json.dumps({"text": "hi"}))],
            usage=SimpleNamespace(
                input_tokens=10,
                cache_read_input_tokens=5,
                cache_creation_input_tokens=0,
                output_tokens=3,
            ),
        )

    monkeypatch.setattr(client._client.messages, "create", create)
    output, meta = client.complete_structured(system="s", user_message="u", tool_schema=SCHEMA)
    assert output == {"text": "hi"}
    assert (meta.provider, meta.input_tokens, meta.output_tokens) == ("anthropic", 15, 3)
    assert sent["output_config"]["format"]["schema"] == SCHEMA.input_schema
    assert not {"tools", "tool_choice", "temperature"} & set(sent)

    def refuse(**kwargs):
        details = SimpleNamespace(explanation="Not this one.")
        return SimpleNamespace(stop_reason="refusal", stop_details=details, content=[])

    monkeypatch.setattr(client._client.messages, "create", refuse)
    with pytest.raises(LLMError, match="declined"):
        client.complete_structured(system="s", user_message="u", tool_schema=SCHEMA)


def test_a_local_server_gets_a_json_schema_response_format(monkeypatch):
    pytest.importorskip("openai")
    client = make_llm_client("local", "qwen2.5", "http://localhost:11434/v1")
    assert client.provider_name == "local"
    assert str(client._client.base_url).startswith("http://localhost:11434/v1")
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        message = SimpleNamespace(content=json.dumps({"text": "hi"}), refusal=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=message)], usage=None
        )

    monkeypatch.setattr(client._client.chat.completions, "create", create)
    output, meta = client.complete_structured(system="s", user_message="u", tool_schema=SCHEMA)
    assert output == {"text": "hi"}
    assert meta.input_tokens == 0
    assert sent["response_format"]["json_schema"]["schema"] == SCHEMA.input_schema
    assert sent["messages"][0] == {"role": "system", "content": "s"}


def test_openai_without_a_key_says_so(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMError, match="OpenAI"):
        make_llm_client("openai", "gpt-test")
