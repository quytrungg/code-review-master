"""A truncated model answer must name its cause, and the evolve call must get its own budget.

Before phase 50, a reasoning model that spent the whole 4096-token budget thinking returned an
empty `content`, which surfaced as "Model returned an empty response". These tests pin the stop
reasons of every transport (blocking and streaming), the per-call `max_tokens` override, and the
OpenCode `reasoning_effort` knob.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import get_settings
from app.services import llm_service

OPENCODE_BASE = "https://opencode.ai/inference/openai/v1"


def _mock_client(monkeypatch, handler):
    """Route every AsyncClient in this test through a MockTransport."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _opencode_credentials() -> llm_service.LLMCredentials:
    return llm_service.LLMCredentials(
        provider="opencode", api_key="oc-key", base_url=OPENCODE_BASE
    )


def _opencode_model() -> llm_service.ModelRef:
    return llm_service.parse_model_id("opencode:deepseek-v4.1-flash")


def test_generate_raises_when_the_relay_reports_length(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": ""},
                        "finish_reason": "length",
                    }
                ],
                "usage": {
                    "prompt_tokens": 17894,
                    "completion_tokens": 4096,
                    "completion_tokens_details": {"reasoning_tokens": 4096},
                },
            },
        )

    _mock_client(monkeypatch, handler)

    with pytest.raises(llm_service.LLMError) as caught:
        asyncio.run(
            llm_service.generate(
                _opencode_credentials(),
                _opencode_model(),
                "system",
                "user",
                json_mode=True,
                purpose="evolve",
            )
        )

    message = str(caught.value)
    assert "OpenCode stopped at its 4096-token output limit" in message
    assert "4096 tokens went to reasoning" in message
    assert "LLM_EVOLVE_MAX_TOKENS" in message
    assert "empty response" not in message


def test_generate_forwards_the_call_budget_and_reasoning_effort(monkeypatch):
    captured: list[dict] = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "{}"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
        )

    _mock_client(monkeypatch, handler)

    asyncio.run(
        llm_service.generate(
            _opencode_credentials(),
            _opencode_model(),
            "system",
            "user",
            json_mode=True,
            purpose="evolve",
            max_tokens=8192,
            reasoning_effort="none",
        )
    )
    asyncio.run(
        llm_service.generate(
            _opencode_credentials(),
            _opencode_model(),
            "system",
            "user",
            purpose="evolve",
        )
    )

    assert captured[0]["max_tokens"] == 8192
    assert captured[0]["reasoning_effort"] == "none"
    assert captured[1]["max_tokens"] == get_settings().llm_max_tokens
    assert "reasoning_effort" not in captured[1]


def test_stream_raises_when_the_relay_reports_length(monkeypatch):
    events = [
        {"choices": [{"index": 0, "delta": {"content": "{"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "length"}]},
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 17894,
                "completion_tokens": 4096,
                "completion_tokens_details": {"reasoning_tokens": 4000},
            },
        },
    ]

    def handler(request):
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
        return httpx.Response(200, content=body)

    _mock_client(monkeypatch, handler)

    with pytest.raises(llm_service.LLMError, match="output limit"):
        asyncio.run(
            llm_service.stream(
                _opencode_credentials(),
                _opencode_model(),
                "system",
                "user",
                on_delta=lambda chunk: None,
                purpose="evolve",
            )
        )


def test_ollama_generate_raises_when_done_reason_is_length(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "done_reason": "length",
                "prompt_eval_count": 120,
                "eval_count": 4096,
            },
        )

    _mock_client(monkeypatch, handler)

    with pytest.raises(llm_service.LLMError, match="Ollama stopped at its output limit"):
        asyncio.run(
            llm_service._generate_ollama(
                "ollama-cloud",
                "https://ollama.com",
                {"Authorization": "Bearer key"},
                "deepseek-v4.1",
                "system",
                "user",
                get_settings(),
            )
        )


def test_ollama_stream_raises_when_done_reason_is_length(monkeypatch):
    frames = [
        {"message": {"content": "partial"}, "done": False},
        {"message": {"content": ""}, "done": True, "done_reason": "length"},
    ]

    def handler(request):
        return httpx.Response(
            200, content="".join(json.dumps(frame) + "\n" for frame in frames)
        )

    _mock_client(monkeypatch, handler)

    with pytest.raises(llm_service.LLMError, match="Ollama stopped at its output limit"):
        asyncio.run(
            llm_service._stream_ollama(
                "ollama-cloud",
                "https://ollama.com",
                {"Authorization": "Bearer key"},
                "deepseek-v4.1",
                "system",
                "user",
                get_settings(),
                lambda chunk: None,
            )
        )


def test_claude_generate_raises_when_stop_reason_is_max_tokens(monkeypatch):
    import anthropic

    class _FakeMessages:
        async def create(self, **kwargs):
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="partial")],
                usage=SimpleNamespace(input_tokens=100, output_tokens=4096),
                stop_reason="max_tokens",
            )

    class _FakeAnthropic:
        def __init__(self, **kwargs):
            self.messages = _FakeMessages()

        async def close(self):
            return None

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeAnthropic)
    credentials = llm_service.LLMCredentials(
        provider="claude", api_key="sk-ant-test-key", base_url=None
    )

    with pytest.raises(llm_service.LLMError, match="Claude stopped at its 4096-token output limit"):
        asyncio.run(
            llm_service._generate_claude(
                credentials, "claude-sonnet-4-5", "system", "user", 4096
            )
        )


def test_claude_stream_raises_when_stop_reason_is_max_tokens(monkeypatch):
    import anthropic

    class _FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        @property
        def text_stream(self):
            async def iterate():
                yield "partial"

            return iterate()

        async def get_final_message(self):
            return SimpleNamespace(
                usage=SimpleNamespace(input_tokens=100, output_tokens=4096),
                stop_reason="max_tokens",
            )

    class _FakeMessages:
        def stream(self, **kwargs):
            return _FakeStream()

    class _FakeAnthropic:
        def __init__(self, **kwargs):
            self.messages = _FakeMessages()

        async def close(self):
            return None

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeAnthropic)
    credentials = llm_service.LLMCredentials(
        provider="claude", api_key="sk-ant-test-key", base_url=None
    )

    with pytest.raises(llm_service.LLMError, match="Claude stopped at its 4096-token output limit"):
        asyncio.run(
            llm_service._stream_claude(
                credentials, "claude-sonnet-4-5", "system", "user", 4096, lambda chunk: None
            )
        )
