"""OpenCode as a model provider: identity, catalog entry, and the Chat Completions transport.

The transport is shared with `openai:` on purpose, so these tests pin what is *different* about an
OpenCode call — the prefix, the base URL, the bearer header, the provider written to the ledger, and
the wording the operator sees when the key is missing or rejected.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.llm_call import LLMCall
from app.services import llm_service
from tests.fixtures import activate, create_llm_key, create_vcs_key, provision


def _mock_client(monkeypatch, handler):
    """Route every AsyncClient in this test through a MockTransport."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


# --- identity ----------------------------------------------------------------------------------


def test_parse_model_id_resolves_the_opencode_prefix():
    ref = llm_service.parse_model_id("opencode:kimi-k2.6")

    assert (ref.provider, ref.name) == ("opencode", "kimi-k2.6")
    assert ref.id == "opencode:kimi-k2.6"
    assert llm_service.DB_PROVIDER[llm_service.OPENCODE] == "opencode"


def test_parse_model_id_rejects_an_empty_opencode_name():
    with pytest.raises(llm_service.LLMError, match="Expected 'claude:"):
        llm_service.parse_model_id("opencode:")


def test_resolve_endpoint_defaults_to_the_console_inference_base():
    credentials = llm_service.LLMCredentials(provider="opencode", api_key="oc-key", base_url=None)

    base, headers = llm_service.resolve_endpoint(
        credentials, llm_service.ModelRef(provider="opencode", name="kimi-k2.6")
    )

    assert base == "https://opencode.ai/inference/openai/v1"
    assert headers == {
        "Authorization": "Bearer oc-key",
        "x-opencode-session": llm_service.OPENCODE_SESSION_ID,
    }
    assert len(headers["x-opencode-session"]) == 32


def test_resolve_endpoint_accepts_a_go_or_custom_base_url():
    credentials = llm_service.LLMCredentials(
        provider="opencode",
        api_key="oc-key",
        base_url="https://opencode.ai/inference/go/openai/v1",
    )

    base, headers = llm_service.resolve_endpoint(
        credentials, llm_service.ModelRef(provider="opencode", name="glm-5.3")
    )

    assert base == "https://opencode.ai/inference/go/openai/v1"
    assert headers["x-opencode-session"] == llm_service.OPENCODE_SESSION_ID


def test_opencode_without_a_key_is_an_error_not_a_request():
    credentials = llm_service.LLMCredentials(provider="opencode", api_key=None, base_url=None)

    with pytest.raises(llm_service.LLMError, match="No OpenCode API key configured"):
        llm_service.resolve_endpoint(
            credentials, llm_service.ModelRef(provider="opencode", name="kimi-k2.6")
        )


# --- catalog -----------------------------------------------------------------------------------


def _probe(models, *, ok=True, detail="85 model(s) available"):
    async def fake_probe(api_key, base_url=None, timeout=10.0, label="OpenAI"):
        return ok, detail, ({"models": models} if models is not None else None)

    return fake_probe


def test_catalog_lists_opencode_models_under_their_own_prefix(client, monkeypatch):
    calls = {}

    async def fake_probe(api_key, base_url=None, timeout=10.0, label="OpenAI"):
        calls["label"] = label
        calls["base_url"] = base_url
        return True, "85 model(s) available", {"models": ["kimi-k2.6", "glm-5.3"]}

    monkeypatch.setattr(llm_service, "probe_openai", fake_probe)
    create_llm_key(client, provider="opencode", api_key="oc-key")

    body = client.get("/api/models").json()
    ids = [model["id"] for model in body["models"]]

    assert "opencode:kimi-k2.6" in ids
    assert "opencode:glm-5.3" in ids

    entry = next(model for model in body["models"] if model["id"] == "opencode:kimi-k2.6")
    assert entry["provider"] == "opencode"
    assert entry["available"] is True
    assert entry["note"] == "OpenCode"
    assert calls == {"label": "OpenCode", "base_url": "https://opencode.ai/inference/openai/v1"}


def test_a_rejected_opencode_key_lists_the_fallback_pair_as_unavailable(client, monkeypatch):
    """OpenCode answers 401 to an unauthenticated catalogue read, so the reason must show."""
    monkeypatch.setattr(
        llm_service,
        "probe_openai",
        _probe(None, ok=False, detail="OpenCode rejected the API key"),
    )
    create_llm_key(client, provider="opencode", api_key="bad-key")

    entries = [
        model
        for model in client.get("/api/models").json()["models"]
        if model["provider"] == "opencode"
    ]

    assert [entry["id"] for entry in entries] == [
        f"opencode:{item['id']}" for item in llm_service.OPENCODE_FALLBACK
    ]
    assert all(entry["available"] is False for entry in entries)
    assert all(entry["note"] == "OpenCode rejected the API key" for entry in entries)


def test_an_empty_listing_falls_back_to_the_keys_default_model(client, monkeypatch):
    monkeypatch.setattr(llm_service, "probe_openai", _probe([]))
    create_llm_key(
        client, provider="opencode", api_key="oc-key", default_model="unlisted-model"
    )

    ids = [
        model["id"]
        for model in client.get("/api/models").json()["models"]
        if model["provider"] == "opencode"
    ]

    assert "opencode:unlisted-model" in ids
    entry = next(
        model
        for model in client.get("/api/models").json()["models"]
        if model["id"] == "opencode:unlisted-model"
    )
    assert entry["available"] is True


def test_active_opencode_key_primes_the_review_picker(client, monkeypatch):
    monkeypatch.setattr(llm_service, "probe_openai", _probe(["kimi-k2.6"]))
    key = create_llm_key(
        client, provider="opencode", api_key="oc-key", default_model="kimi-k2.6"
    )
    create_vcs_key(client)
    activate(client, llm_key_id=key["id"])

    assert client.get("/api/models").json()["preferred"] == "opencode:kimi-k2.6"


# --- transport ---------------------------------------------------------------------------------


def test_generate_sends_a_chat_completions_request_and_records_the_provider(monkeypatch):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["session"] = request.headers.get("x-opencode-session")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "[]"}}],
                "usage": {"prompt_tokens": 800, "completion_tokens": 200},
            },
        )

    _mock_client(monkeypatch, handler)
    credentials = llm_service.LLMCredentials(
        provider="opencode",
        api_key="oc-key",
        base_url="https://opencode.ai/inference/openai/v1",
    )
    model = llm_service.parse_model_id("opencode:kimi-k2.6")

    result = asyncio.run(
        llm_service.generate(credentials, model, "system", "user", json_mode=True, purpose="ingest")
    )

    assert result.provider == "opencode"
    assert result.text == "[]"
    assert (result.prompt_tokens, result.completion_tokens) == (800, 200)
    assert captured["url"] == "https://opencode.ai/inference/openai/v1/chat/completions"
    assert captured["auth"] == "Bearer oc-key"
    assert captured["session"] == llm_service.OPENCODE_SESSION_ID
    assert captured["payload"]["model"] == "kimi-k2.6"
    assert captured["payload"]["response_format"] == {"type": "json_object"}

    with SessionLocal() as db:
        row = db.scalars(select(LLMCall).order_by(LLMCall.id.desc())).first()
        assert row is not None
        assert (row.provider, row.model) == ("opencode", "kimi-k2.6")
        assert row.purpose == "ingest"
        assert row.ok is True
        db.delete(row)
        db.commit()


def test_a_rejected_opencode_key_names_opencode_in_the_error(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": "unauthorized"})

    _mock_client(monkeypatch, handler)
    credentials = llm_service.LLMCredentials(
        provider="opencode", api_key="bad-key", base_url=None
    )

    with pytest.raises(llm_service.LLMError, match="OpenCode rejected the API key"):
        asyncio.run(
            llm_service.generate(
                credentials,
                llm_service.parse_model_id("opencode:kimi-k2.6"),
                "system",
                "user",
                purpose="ingest",
            )
        )


def test_stream_routes_opencode_through_the_sse_reader(monkeypatch):
    events = [
        {"choices": [{"index": 0, "delta": {"content": "You are"}}]},
        {"choices": [{"index": 0, "delta": {"content": " right."}}]},
        {"choices": [], "usage": {"prompt_tokens": 90, "completion_tokens": 12}},
    ]

    def handler(request):
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
        return httpx.Response(200, content=body)

    _mock_client(monkeypatch, handler)
    credentials = llm_service.LLMCredentials(
        provider="opencode", api_key="oc-key", base_url=None
    )
    deltas: list[str] = []

    result = asyncio.run(
        llm_service.stream(
            credentials,
            llm_service.parse_model_id("opencode:kimi-k2.6"),
            "system",
            "user",
            on_delta=deltas.append,
            purpose="discuss",
        )
    )

    assert deltas == ["You are", " right."]
    assert result.text == "You are right."
    assert result.provider == "opencode"
    assert (result.prompt_tokens, result.completion_tokens) == (90, 12)


# --- probe -------------------------------------------------------------------------------------


def test_key_test_probes_opencode_with_its_own_label(client, monkeypatch):
    seen = {}

    async def fake_probe(api_key, base_url=None, timeout=10.0, label="OpenAI"):
        seen["label"] = label
        seen["base_url"] = base_url
        return True, "85 model(s) available", {"models": ["kimi-k2.6"]}

    monkeypatch.setattr(llm_service, "probe_openai", fake_probe)
    key = create_llm_key(client, provider="opencode", api_key="oc-key")

    response = client.post(f"/api/keys/llm/{key['id']}/test")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "detail": "85 model(s) available",
        "metadata": {"models": ["kimi-k2.6"]},
    }
    assert seen == {
        "label": "OpenCode",
        "base_url": "https://opencode.ai/inference/openai/v1",
    }


def test_opencode_key_is_stored_masked_and_revealable(client):
    key = create_llm_key(client, provider="opencode", api_key="oc-secret-value-1234")

    listed = client.get("/api/keys/llm").json()
    row = next(item for item in listed if item["id"] == key["id"])
    assert row["provider"] == "opencode"
    assert row["api_key"] is None
    assert row["api_key_masked"] != "oc-secret-value-1234"
    assert row["api_key_masked"].endswith("1234")

    revealed = client.get("/api/keys/llm?reveal=true").json()
    assert next(item for item in revealed if item["id"] == key["id"])["api_key"] == (
        "oc-secret-value-1234"
    )


def test_an_unreachable_probe_names_opencode_and_returns_no_models(monkeypatch):
    """The catalog falls back to the static pair; this pins the reason it reports."""

    def handler(request):
        raise httpx.ConnectError("no route to host")

    _mock_client(monkeypatch, handler)

    ok, detail, metadata = asyncio.run(
        llm_service.probe_openai(
            "oc-key", base_url="https://opencode.ai/inference/openai/v1", label="OpenCode"
        )
    )

    assert ok is False
    assert metadata is None
    assert detail.startswith("Could not reach OpenCode at https://opencode.ai/inference/openai/v1")
