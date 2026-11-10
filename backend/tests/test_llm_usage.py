"""Token extraction, cost estimation and the ledger's failure boundary.

The adapters themselves never run here: usage parsing is a pure function over the payload shape
each provider returns, so a recorded body is enough. The one end-to-end case stubs the Ollama
adapter instead of `generate`, which is what exercises the real `generate` → `ledger.record` path
without touching the network.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest
from sqlalchemy import func, select, text

from app.core.pricing import estimate_cost, price_for
from app.db.session import SessionLocal
from app.models.llm_call import LLMCall
from app.services import github_service, ledger, llm_service
from tests.fixtures import PR_URL, llm_result, provision
from tests.test_review_pipeline import FINDINGS, fake_fetch_diff, fake_fetch_pr_async

# --- recorded payload shapes (trimmed to what the ledger reads) -------------------------------

ANTHROPIC_BODY = {
    "id": "msg_01",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-4-5-20250929",
    "content": [{"type": "text", "text": "[]"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 1234, "output_tokens": 456},
}

ANTHROPIC_STREAM = [
    {"type": "message_start", "message": {"id": "msg_01", "usage": {"input_tokens": 1234}}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "[]"}},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 456}},
    {"type": "message_stop"},
]

OPENAI_BODY = {
    "id": "chatcmpl-1",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "[]"}}],
    "usage": {"prompt_tokens": 800, "completion_tokens": 200, "total_tokens": 1000},
}

OLLAMA_BODY = {
    "model": "llama3",
    "message": {"role": "assistant", "content": "[]"},
    "done": True,
    "prompt_eval_count": 640,
    "eval_count": 128,
}


# --- usage parsing ----------------------------------------------------------------------------


def test_claude_usage_reads_a_messages_body():
    assert llm_service.claude_usage(ANTHROPIC_BODY) == (1234, 456)


def test_claude_usage_merges_stream_events():
    assert llm_service.claude_usage(ANTHROPIC_STREAM) == (1234, 456)


def test_claude_usage_without_a_usage_block_is_null():
    assert llm_service.claude_usage({"content": []}) == (None, None)


def test_openai_usage_reads_the_usage_object():
    assert llm_service.openai_usage(OPENAI_BODY) == (800, 200)


def test_openai_usage_absent_is_null_not_zero():
    assert llm_service.openai_usage({"choices": [{"message": {"content": "[]"}}]}) == (None, None)


def test_ollama_usage_reads_the_eval_counters():
    assert llm_service.ollama_usage(OLLAMA_BODY) == (640, 128)


def test_ollama_usage_missing_counters_are_null():
    body = {"message": {"content": "[]"}, "done": True}
    assert llm_service.ollama_usage(body) == (None, None)


def test_ollama_usage_zero_counters_are_null():
    """A local model that reports 0 evaluated tokens reported nothing; NULL is the honest value."""
    body = {"message": {"content": "[]"}, "prompt_eval_count": 0, "eval_count": 0}
    assert llm_service.ollama_usage(body) == (None, None)


# --- pricing ----------------------------------------------------------------------------------


def test_price_matches_by_prefix_and_prefers_the_longest():
    assert price_for("claude-3-haiku-20240307") == {"input": 0.25, "output": 1.25}
    # `gpt-4o` is a prefix of `gpt-4o-mini`; the more specific rate must win.
    assert price_for("gpt-4o-mini") == {"input": 0.15, "output": 0.60}
    assert price_for("gpt-4o") == {"input": 2.50, "output": 10.00}
    # `glm-5.3` is a prefix of `glm-5.3-flash`, and `kimi-k3` of `kimi-k3.1-pro`.
    assert price_for("glm-5.3-flash") == {"input": 0.15, "output": 0.50}
    assert price_for("kimi-k3.1-pro") == {"input": 2.00, "output": 10.00}


def test_unknown_model_has_no_price():
    assert price_for("gpt-5-codex") is None
    assert estimate_cost("openai", "gpt-5-codex", 1000, 500) is None


def test_cost_is_per_million_tokens():
    assert estimate_cost("claude", "claude-sonnet-4-5-20250929", 1_000_000, 1_000_000) == 18.0


def test_cost_needs_both_counts():
    assert estimate_cost("claude", "claude-3-5-sonnet", None, 500) is None


def test_ollama_local_is_free_and_ollama_cloud_is_metered():
    # A local daemon has no per-token bill; the cloud API is priced per token like any other.
    assert estimate_cost("ollama-local", "llama3", 640, 128) == 0.0
    assert price_for("deepseek-v4.1-flash:1017") == {"input": 0.30, "output": 1.20}
    assert estimate_cost("ollama-cloud", "deepseek-v4.1-flash:1017", 1_000_000, 1_000_000) == 1.5
    # A cloud model with no published row stays unknown rather than silently free.
    assert estimate_cost("ollama-cloud", "some-unlisted-model", 640, 128) is None


# --- the ledger -------------------------------------------------------------------------------


def test_ledger_stores_null_tokens_for_a_silent_model():
    ledger.record(
        llm_result("[]", prompt_tokens=None, completion_tokens=None, provider="ollama-local"),
        purpose="ingest",
    )
    with SessionLocal() as db:
        row = db.scalars(select(LLMCall).order_by(LLMCall.id.desc())).first()
        assert row is not None
        assert row.prompt_tokens is None
        assert row.completion_tokens is None
        assert row.total_tokens is None
        assert row.estimated_cost_usd is None
        assert row.ok is True
        # This row belongs to no review, so no cascade removes it: delete the fixture explicitly.
        db.delete(row)
        db.commit()


def test_ledger_records_a_failed_call_with_its_error_class():
    ledger.record(
        llm_result(
            "",
            prompt_tokens=None,
            completion_tokens=None,
            ok=False,
            error_class="RateLimitError",
        ),
        purpose="discuss",
    )
    with SessionLocal() as db:
        row = db.scalars(select(LLMCall).order_by(LLMCall.id.desc())).first()
        assert row.ok is False
        assert row.error_class == "RateLimitError"
        db.delete(row)
        db.commit()


def test_ledger_failure_is_a_warning_and_never_an_exception(monkeypatch, caplog):
    def explode():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(ledger, "SessionLocal", explode)
    with caplog.at_level(logging.WARNING, logger="app.services.ledger"):
        ledger.record(llm_result("[]"), purpose="ingest")

    assert any("Could not record an LLM call" in record.message for record in caplog.records)


def test_a_missing_key_is_not_recorded_as_a_call(client):
    """No request was sent, so there is no call to bill: the caller gets the error instead."""
    credentials = llm_service.LLMCredentials(provider="claude", api_key=None, base_url=None)
    model = llm_service.parse_model_id("claude:claude-sonnet-4-5-20250929")

    with SessionLocal() as db:
        before = db.execute(select(func.count()).select_from(LLMCall)).scalar_one()

    with pytest.raises(llm_service.LLMError, match="No Claude API key"):
        asyncio.run(
            llm_service.generate(credentials, model, "system", "user", purpose="ingest")
        )

    with SessionLocal() as db:
        assert db.execute(select(func.count()).select_from(LLMCall)).scalar_one() == before


# --- end to end through `generate` -------------------------------------------------------------

INGEST_LATENCY_MS = 42


def stub_ollama(monkeypatch, payload: str = json.dumps(FINDINGS)):
    async def fetch_comments(token, repo_full_name, number, base_url=None):
        return []

    async def adapter(provider, base_url, headers, name, system_prompt, user_prompt, config, json_mode=False):
        return llm_service.LLMResult(
            text=payload,
            prompt_tokens=1200,
            completion_tokens=300,
            latency_ms=INGEST_LATENCY_MS,
            provider=provider,
            model=name,
        )

    monkeypatch.setattr(github_service, "fetch_pr", fake_fetch_pr_async)
    monkeypatch.setattr(github_service, "fetch_diff", fake_fetch_diff)
    monkeypatch.setattr(github_service, "fetch_review_comments", fetch_comments)
    monkeypatch.setattr(llm_service, "_generate_ollama", adapter)


def test_ingest_writes_one_ledger_row_and_the_header_usage(client, monkeypatch):
    from tests.conftest import start_review, TEST_EMAIL

    stub_ollama(monkeypatch)
    provision(client)

    review = start_review(client, PR_URL, "ollama-local:llama3")
    assert review["status"] == "draft"

    with SessionLocal() as db:
        user_id = db.execute(
            text("SELECT id FROM users WHERE email = :email"), {"email": TEST_EMAIL}
        ).scalar_one()
        rows = list(
            db.scalars(select(LLMCall).where(LLMCall.review_id == review["id"])).all()
        )
    assert len(rows) == 1
    row = rows[0]
    assert row.purpose == "ingest"
    assert row.provider == "ollama-local"
    assert row.model == "llama3"
    assert (row.prompt_tokens, row.completion_tokens, row.total_tokens) == (1200, 300, 1500)
    assert row.latency_ms == INGEST_LATENCY_MS
    assert row.estimated_cost_usd == 0.0  # a local daemon has no per-token price
    assert row.ok is True
    assert user_id  # ownership is reached through the review

    # The header line the UI renders comes from the same rows.
    detail = client.get(f"/api/reviews/{review['id']}").json()
    assert detail["usage"]["calls"] == 1
    assert detail["usage"]["total_tokens"] == 1500
    assert detail["usage"]["estimated_cost_usd"] == 0.0
    assert detail["usage"]["latency_ms"] == INGEST_LATENCY_MS

    # The list stays a single query and carries no usage.
    listing = client.get("/api/reviews").json()
    assert listing[0]["usage"] is None


def test_a_broken_ledger_still_lets_the_review_finish(client, monkeypatch, caplog):
    from tests.conftest import start_review

    def explode():
        raise RuntimeError("database is locked")

    stub_ollama(monkeypatch)
    monkeypatch.setattr(ledger, "SessionLocal", explode)
    provision(client)

    with caplog.at_level(logging.WARNING, logger="app.services.ledger"):
        review = start_review(client, PR_URL, "ollama-local:llama3")

    assert review["status"] == "draft"
    assert review["thread_count"] == 2
    assert any("Could not record an LLM call" in record.message for record in caplog.records)
    with SessionLocal() as db:
        assert db.scalars(select(LLMCall).where(LLMCall.review_id == review["id"])).first() is None


def test_a_failed_call_is_recorded_and_still_fails_the_review(client, monkeypatch):
    """The review fails as before; the ledger row says which exception class did it."""
    from tests.conftest import start_review

    async def adapter(*args, **kwargs):
        # Wrapped the way the real adapters do it: the cause is the transport failure.
        raise llm_service.LLMError("Could not reach Ollama") from ConnectionResetError("reset")

    stub_ollama(monkeypatch)
    monkeypatch.setattr(llm_service, "_generate_ollama", adapter)
    provision(client)

    review = start_review(client, PR_URL, "ollama-local:llama3")
    assert review["status"] == "failed"

    with SessionLocal() as db:
        row = db.scalars(select(LLMCall).where(LLMCall.review_id == review["id"])).first()
    assert row.ok is False
    assert row.error_class == "ConnectionResetError"
    assert row.prompt_tokens is None
    assert row.latency_ms >= 0
