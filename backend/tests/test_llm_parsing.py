from __future__ import annotations

import pytest

from app.services.llm_service import (
    LLMCredentials,
    LLMError,
    ModelRef,
    extract_json_array,
    parse_model_id,
    resolve_endpoint,
)


def test_plain_array():
    assert extract_json_array('[{"filePath": "a.py"}]') == [{"filePath": "a.py"}]


def test_fenced_array():
    text = '```json\n[{"filePath": "a.py", "lineNumber": 1}]\n```'
    assert extract_json_array(text) == [{"filePath": "a.py", "lineNumber": 1}]


def test_prose_around_array():
    text = 'Here are my findings:\n[{"filePath": "a.py"}]\nHope this helps.'
    assert extract_json_array(text) == [{"filePath": "a.py"}]


def test_wrapped_object_with_findings_key():
    assert extract_json_array('{"findings": [{"filePath": "a.py"}]}') == [{"filePath": "a.py"}]


def test_single_finding_object_is_wrapped():
    assert extract_json_array('{"filePath": "a.py", "lineNumber": 2}') == [
        {"filePath": "a.py", "lineNumber": 2}
    ]


def test_empty_array_is_valid():
    assert extract_json_array("[]") == []


@pytest.mark.parametrize("text", ["", "   ", "I could not review this.", "{not json}"])
def test_unparsable_text_raises(text):
    with pytest.raises(LLMError):
        extract_json_array(text)


def test_parse_model_id_defaults_to_cloud_and_keeps_local_distinct():
    cloud = parse_model_id("ollama-cloud:gpt-oss:20b")
    assert (cloud.provider, cloud.name) == ("ollama-cloud", "gpt-oss:20b")

    local = parse_model_id("ollama-local:qwen2.5-coder:14b")
    assert (local.provider, local.name, local.id) == (
        "ollama-local",
        "qwen2.5-coder:14b",
        "ollama-local:qwen2.5-coder:14b",
    )

    assert parse_model_id("claude:claude-sonnet-4-5-20250929").provider == "claude"


def test_legacy_ollama_prefix_resolves_to_cloud():
    ref = parse_model_id("ollama:qwen2.5-coder:14b")
    assert (ref.provider, ref.name) == ("ollama-cloud", "qwen2.5-coder:14b")
    assert ref.id == "ollama-cloud:qwen2.5-coder:14b"


@pytest.mark.parametrize("bad", ["", "llama3", "claude:", "ollama-cloud:", "nope:model"])
def test_parse_model_id_rejects_unknown_providers(bad):
    with pytest.raises(LLMError):
        parse_model_id(bad)


def test_openai_prefix_is_supported():
    ref = parse_model_id("openai:gpt-5-codex")
    assert (ref.provider, ref.name) == ("openai", "gpt-5-codex")


def test_resolve_endpoint_requires_a_cloud_key():
    credentials = LLMCredentials(provider="ollama_cloud", api_key=None, base_url=None)
    with pytest.raises(LLMError, match="No Ollama Cloud API key"):
        resolve_endpoint(credentials, ModelRef(provider="ollama-cloud", name="gpt-oss:20b"))


def test_resolve_endpoint_sends_bearer_for_cloud_and_none_for_local():
    credentials = LLMCredentials(
        provider="ollama_cloud", api_key="key-123", base_url="https://ollama.com"
    )

    cloud_url, cloud_headers = resolve_endpoint(
        credentials, ModelRef(provider="ollama-cloud", name="gpt-oss:20b")
    )
    assert cloud_url.endswith("ollama.com")
    assert cloud_headers == {"Authorization": "Bearer key-123"}

    local = LLMCredentials(
        provider="ollama_local", api_key=None, base_url="http://127.0.0.1:11434/"
    )
    local_url, local_headers = resolve_endpoint(local, ModelRef(provider="ollama-local", name="llama3"))
    assert local_url == "http://127.0.0.1:11434"
    assert local_headers == {}


def test_resolve_endpoint_uses_bearer_auth_for_openai():
    credentials = LLMCredentials(provider="openai", api_key="sk-x", base_url="https://api.test/v1")
    url, headers = resolve_endpoint(credentials, ModelRef(provider="openai", name="gpt-5-codex"))
    assert url == "https://api.test/v1"
    assert headers == {"Authorization": "Bearer sk-x"}
