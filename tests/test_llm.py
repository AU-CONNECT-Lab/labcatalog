import base64
import json
from types import SimpleNamespace

import pytest

from labcatalog.exceptions import LLMError
from labcatalog.llm import Image, ToolSchema, make_llm_client

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
    client = make_llm_client("local", "qwen2.5", "http://127.0.0.1:11434/v1")
    assert client.provider_name == "local"
    assert str(client._client.base_url).startswith("http://127.0.0.1:11434/v1")
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
    assert sent["max_tokens"] == 16000


def test_a_local_model_that_runs_long_stops_with_a_message_and_is_not_asked_again(monkeypatch):
    openai = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx")
    client = make_llm_client("local", "qwen2.5", "http://127.0.0.1:11434/v1")
    calls = []

    def time_out(**kwargs):
        calls.append(kwargs)
        raise openai.APITimeoutError(request=httpx.Request("POST", "http://127.0.0.1"))

    monkeypatch.setattr(client._client.chat.completions, "create", time_out)
    with pytest.raises(LLMError, match="call failed"):
        client.complete_structured(system="s", user_message="u", tool_schema=SCHEMA)
    assert len(calls) == 1

    def run_long(**kwargs):
        message = SimpleNamespace(content="{", refusal=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="length", message=message)], usage=None
        )

    monkeypatch.setattr(client._client.chat.completions, "create", run_long)
    with pytest.raises(LLMError, match="stopped after 16000 tokens"):
        client.complete_structured(system="s", user_message="u", tool_schema=SCHEMA)


def test_openai_in_the_cloud_gets_no_token_cap(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    client = make_llm_client("openai", "gpt-test")
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        message = SimpleNamespace(content=json.dumps({"text": "hi"}), refusal=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=message)], usage=None
        )

    monkeypatch.setattr(client._client.chat.completions, "create", create)
    client.complete_structured(system="s", user_message="u", tool_schema=SCHEMA)
    assert "max_tokens" not in sent


def test_openai_without_a_key_says_so(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMError, match="OpenAI"):
        make_llm_client("openai", "gpt-test")


PICTURE = Image("image/png", b"png bytes")


def test_pictures_go_before_the_text_for_anthropic_and_after_it_for_a_local_server(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    client = make_llm_client("anthropic", "claude-test")
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        usage = SimpleNamespace(
            input_tokens=1,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            output_tokens=1,
        )
        text = SimpleNamespace(type="text", text=json.dumps({"text": "hi"}))
        return SimpleNamespace(stop_reason="end_turn", content=[text], usage=usage)

    monkeypatch.setattr(client._client.messages, "create", create)
    client.complete_structured(system="s", user_message="u", tool_schema=SCHEMA, images=[PICTURE])
    first, last = sent["messages"][0]["content"]
    assert first["type"] == "image" and first["source"]["media_type"] == "image/png"
    assert first["source"]["data"] == base64.b64encode(b"png bytes").decode()
    assert last == {"type": "text", "text": "u"}

    pytest.importorskip("openai")
    local = make_llm_client("local", "qwen3-vl", "http://127.0.0.1:11434/v1")

    def answer(**kwargs):
        sent.update(kwargs)
        message = SimpleNamespace(content=json.dumps({"text": "hi"}), refusal=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=message)], usage=None
        )

    monkeypatch.setattr(local._client.chat.completions, "create", answer)
    local.complete_structured(system="s", user_message="u", tool_schema=SCHEMA, images=[PICTURE])
    text, picture = sent["messages"][1]["content"]
    assert text == {"type": "text", "text": "u"}
    url = "data:image/png;base64," + base64.b64encode(b"png bytes").decode()
    assert picture == {"type": "image_url", "image_url": {"url": url}}


def test_gemini_asks_for_json_by_the_schema_with_the_pictures_first(monkeypatch):
    pytest.importorskip("google.genai")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    client = make_llm_client("gemini", "gemini-test")
    sent = {}

    def generate(**kwargs):
        sent.update(kwargs)
        usage = SimpleNamespace(
            prompt_token_count=12, candidates_token_count=3, thoughts_token_count=5
        )
        candidate = SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))
        return SimpleNamespace(
            candidates=[candidate], text=json.dumps({"text": "hi"}), usage_metadata=usage
        )

    monkeypatch.setattr(client._client.models, "generate_content", generate)
    output, meta = client.complete_structured(
        system="s", user_message="u", tool_schema=SCHEMA, images=[PICTURE]
    )
    assert output == {"text": "hi"}
    assert (meta.provider, meta.input_tokens, meta.output_tokens) == ("gemini", 12, 8)
    config = sent["config"]
    assert config.response_json_schema == SCHEMA.input_schema
    assert (config.system_instruction, config.response_mime_type) == ("s", "application/json")
    picture, text = sent["contents"]
    assert picture.inline_data.data == b"png bytes" and text == "u"

    def cut(**kwargs):
        candidate = SimpleNamespace(finish_reason=SimpleNamespace(name="MAX_TOKENS"))
        return SimpleNamespace(candidates=[candidate], text="{", usage_metadata=None)

    monkeypatch.setattr(client._client.models, "generate_content", cut)
    with pytest.raises(LLMError, match="cut off"):
        client.complete_structured(system="s", user_message="u", tool_schema=SCHEMA)
