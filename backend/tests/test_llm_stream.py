"""Streaming adapters: NDJSON/SSE/SDK streams produce one LLMResult like the blocking calls."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import get_settings
from app.services import llm_service


def _mock_client(monkeypatch, handler):
    """Route every AsyncClient in this test through a MockTransport."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def test_ollama_stream_assembles_text_and_terminal_usage(monkeypatch):
    frames = [
        {"message": {"content": "You are"}, "done": False},
        {"message": {"content": " right"}, "done": False},
        {"message": {"content": " — allowlist it."}, "done": False},
        {"message": {"content": ""}, "done": True, "prompt_eval_count": 120, "eval_count": 18},
    ]
    captured = {}

    def handler(request):
        captured["payload"] = json.loads(request.content)
        body = "".join(json.dumps(frame) + "\n" for frame in frames)
        return httpx.Response(200, content=body)

    _mock_client(monkeypatch, handler)

    deltas: list[str] = []
    result = asyncio.run(
        llm_service._stream_ollama(
            "ollama-local",
            "http://localhost:11434",
            {},
            "llama3",
            "system",
            "user",
            get_settings(),
            deltas.append,
        )
    )

    assert result.text == "You are right — allowlist it."
    assert deltas == ["You are", " right", " — allowlist it."]
    assert result.prompt_tokens == 120
    assert result.completion_tokens == 18
    assert result.provider == "ollama-local"
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["options"]["num_ctx"] == llm_service.OLLAMA_NUM_CTX
    # Discussion replies are prose: streaming must never force JSON mode.
    assert "format" not in captured["payload"]


def test_ollama_stream_maps_http_errors_like_the_blocking_call(monkeypatch):
    def handler(request):
        return httpx.Response(404, content=b'{"error": "model not found"}')

    _mock_client(monkeypatch, handler)

    with pytest.raises(llm_service.LLMError, match="does not have the model 'nope'"):
        asyncio.run(
            llm_service._stream_ollama(
                "ollama-local",
                "http://localhost:11434",
                {},
                "nope",
                "system",
                "user",
                get_settings(),
                lambda chunk: None,
            )
        )


def test_openai_stream_reads_deltas_and_the_terminal_usage_frame(monkeypatch):
    body = "".join(
        [
            'data: {"choices": [{"delta": {"role": "assistant"}}]}\n\n',
            'data: {"choices": [{"delta": {"content": "Fixed "}}]}\n\n',
            'data: {"choices": [{"delta": {"content": "answer."}}]}\n\n',
            'data: {"choices": [], "usage": {"prompt_tokens": 41, "completion_tokens": 9}}\n\n',
            "data: [DONE]\n\n",
        ]
    )
    captured = {}

    def handler(request):
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, content=body, headers={"Content-Type": "text/event-stream"})

    _mock_client(monkeypatch, handler)

    deltas: list[str] = []
    result = asyncio.run(
        llm_service._stream_openai(
            "https://api.openai.com/v1",
            {"Authorization": "Bearer sk-test"},
            "gpt-5-codex",
            "system",
            "user",
            get_settings(),
            deltas.append,
        )
    )

    assert result.text == "Fixed answer."
    assert deltas == ["Fixed ", "answer."]
    assert result.prompt_tokens == 41
    assert result.completion_tokens == 9
    assert captured["payload"]["stream"] is True
    # Without this the usage frame never arrives and the ledger reads NULL.
    assert captured["payload"]["stream_options"] == {"include_usage": True}


def test_claude_stream_merges_text_and_usage(monkeypatch):
    import anthropic

    captured = {}

    class _FakeStream:
        def __init__(self, chunks):
            self._chunks = chunks

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        @property
        def text_stream(self):
            async def iterate():
                for chunk in self._chunks:
                    yield chunk

            return iterate()

        async def get_final_message(self):
            return SimpleNamespace(usage=SimpleNamespace(input_tokens=51, output_tokens=7))

    class _FakeMessages:
        def stream(self, **kwargs):
            captured["call"] = kwargs
            return _FakeStream(["Use an ", "allowlist."])

    class _FakeAnthropic:
        def __init__(self, **kwargs):
            self.messages = _FakeMessages()

        async def close(self):
            captured["closed"] = True

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeAnthropic)

    credentials = llm_service.LLMCredentials(
        provider="claude", api_key="sk-ant-test-key", base_url=None
    )
    deltas: list[str] = []
    result = asyncio.run(
        llm_service._stream_claude(credentials, "claude-sonnet-4-5", "system", "user", 4096, deltas.append)
    )

    assert result.text == "Use an allowlist."
    assert deltas == ["Use an ", "allowlist."]
    assert result.prompt_tokens == 51
    assert result.completion_tokens == 7
    assert captured["call"]["system"] == "system"
    assert captured["closed"] is True


def test_stream_records_success_and_failure_in_the_ledger(client, monkeypatch):
    """The wrapper owns the ledger: patched adapters still leave one row per call."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.llm_call import LLMCall
    from tests.fixtures import llm_result

    async def good(provider, base_url, headers, name, system_prompt, user_prompt, config, on_delta):
        on_delta("ok")
        return llm_result("ok")

    monkeypatch.setattr(llm_service, "_stream_ollama", good)

    credentials = llm_service.LLMCredentials(provider="ollama_local", api_key=None, base_url=None)
    model = llm_service.parse_model_id("ollama-local:llama3")
    result = asyncio.run(
        llm_service.stream(
            credentials, model, "system", "user", on_delta=lambda chunk: None, purpose="discuss"
        )
    )
    assert result.text == "ok"

    async def boom(provider, base_url, headers, name, system_prompt, user_prompt, config, on_delta):
        raise llm_service.LLMError("connection refused")

    monkeypatch.setattr(llm_service, "_stream_ollama", boom)
    with pytest.raises(llm_service.LLMError):
        asyncio.run(
            llm_service.stream(
                credentials, model, "system", "user", on_delta=lambda chunk: None, purpose="discuss"
            )
        )

    with SessionLocal() as db:
        rows = db.scalars(select(LLMCall).order_by(LLMCall.id)).all()
        ours = [row for row in rows if row.purpose == "discuss"][-2:]
        assert [row.ok for row in ours] == [True, False]
        assert ours[0].prompt_tokens == 1200
        assert ours[1].error_class == "LLMError"
        for row in ours:  # the shared database keeps rows between tests; clean up our own
            db.delete(row)
        db.commit()
