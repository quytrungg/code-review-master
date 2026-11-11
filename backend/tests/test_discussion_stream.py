"""The streaming discussion endpoint and its per-thread persistence/cancel semantics."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, cast

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.llm_call import LLMCall
from app.models.review import CodeReview
from app.schemas.review import DiscussThread
from app.services import discussion, llm_service
from tests.fixtures import PR_URL, as_result, llm_result, provision
from tests.test_review_pipeline import FINDINGS, configure


def seed_review(client, monkeypatch) -> dict:
    from tests.conftest import start_review

    configure(monkeypatch, json.dumps(FINDINGS))
    provision(client)
    return start_review(client, PR_URL, "ollama-local:llama3")


def _verdict_stub(monkeypatch):
    async def reply(*args, **kwargs):
        return json.dumps({"verdict": "APPROVE", "confidence": 88, "rationale": "Resolved."})

    monkeypatch.setattr(llm_service, "generate", as_result(reply))


def _stream_stub(monkeypatch, responder):
    """Patch one level below the wrapper: the ledger and `stream()` still run for real."""

    async def fake(provider, base_url, headers, name, system_prompt, user_prompt, config, on_delta):
        text = responder(user_prompt)
        midpoint = max(1, len(text) // 2)
        for chunk in (text[:midpoint], text[midpoint:]):
            on_delta(chunk)
        return llm_result(text)

    monkeypatch.setattr(llm_service, "_stream_ollama", fake)


def _parse_sse(body: str):
    events = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        name = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        events.append((name, data))
    return events


def test_streamed_discussion_emits_per_thread_events_and_persists(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    thread_ids = [thread["id"] for thread in review["threads"]]

    def responder(user_prompt):
        assert "Conversation so far" in user_prompt
        assert "Reviewer (user)" in user_prompt
        if "allowlist" in user_prompt:
            return "Yes — an allowlist is safer."
        return "Keep the log line."

    _stream_stub(monkeypatch, responder)
    _verdict_stub(monkeypatch)

    with client.stream(
        "POST",
        f"/api/reviews/{review['id']}/discuss/stream",
        json={
            "threads": [
                {"thread_id": thread_ids[0], "message": "Can we use an allowlist?"},
                {"thread_id": thread_ids[1], "message": "Is the log line necessary?"},
            ]
        },
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"
        events = _parse_sse(response.read().decode())

    started = [data["thread_id"] for name, data in events if name == "thread_started"]
    assert sorted(started) == sorted(thread_ids)

    for thread_id in thread_ids:
        deltas = [
            data["text"] for name, data in events
            if name == "delta" and data["thread_id"] == thread_id
        ]
        assert len(deltas) == 2
        done = next(
            (data for name, data in events if name == "thread_done" and data["thread_id"] == thread_id),
            None,
        )
        assert done is not None and done["message_id"] > 0

    last = events[-1]
    assert last[0] == "done"
    assert last[1]['answered'] == 2
    assert last[1]["failed"] == 0
    assert last[1]["opinion_refreshed"] is True

    stored = client.get(f"/api/reviews/{review['id']}").json()
    assert stored["status"] == "in_discussion"
    threads = {thread["id"]: thread for thread in stored["threads"]}
    first = threads[thread_ids[0]]["messages"]
    assert [message["role"] for message in first] == ["assistant", "user", "assistant"]
    assert first[1]["content"] == "Can we use an allowlist?"
    assert first[2]["content"] == "Yes — an allowlist is safer."

    with SessionLocal() as db:
        rows = db.scalars(
            select(LLMCall).where(LLMCall.review_id == review["id"], LLMCall.purpose == "discuss")
        ).all()
        assert len(rows) == 2
        assert all(row.ok for row in rows)


def test_streamed_thread_error_leaves_the_failed_thread_untouched(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    thread_ids = [thread["id"] for thread in review["threads"]]

    def responder(user_prompt):
        if "log line" in user_prompt:
            raise llm_service.LLMError("Ollama does not have the model 'nope'.")
        return "Fixed answer."

    _stream_stub(monkeypatch, responder)
    _verdict_stub(monkeypatch)

    with client.stream(
        "POST",
        f"/api/reviews/{review['id']}/discuss/stream",
        json={
            "threads": [
                {"thread_id": thread_ids[0], "message": "Why?"},
                {"thread_id": thread_ids[1], "message": "Is the log line necessary?"},
            ]
        },
    ) as response:
        events = _parse_sse(response.read().decode())

    error = next(data for name, data in events if name == "thread_error")
    assert error["thread_id"] == thread_ids[1]
    assert "nope" in error["error"]

    last = events[-1]
    assert last[0] == "done"
    assert last[1]["answered"] == 1
    assert last[1]["failed"] == 1

    stored = client.get(f"/api/reviews/{review['id']}").json()
    assert stored["status"] == "in_discussion"
    threads = {thread["id"]: thread for thread in stored["threads"]}
    # The streaming rule: a failed thread persists nothing, not even the reviewer's message —
    # the draft stays client-side so it can be retried.
    assert [message["role"] for message in threads[thread_ids[0]]["messages"]] == [
        "assistant",
        "user",
        "assistant",
    ]
    assert [message["role"] for message in threads[thread_ids[1]]["messages"]] == ["assistant"]

    with SessionLocal() as db:
        failed = db.scalars(
            select(LLMCall).where(
                LLMCall.review_id == review["id"],
                LLMCall.purpose == "discuss",
                LLMCall.ok.is_(False),
            )
        ).all()
        assert len(failed) == 1
        assert failed[0].thread_id == thread_ids[1]
        assert failed[0].error_class == "LLMError"


def test_cancelled_stream_keeps_completed_thread_and_writes_nothing_else(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    thread_ids = [thread["id"] for thread in review["threads"]]

    async def stream(credentials, model, system_prompt, user_prompt, *, on_delta, **kwargs):
        if "allowlist" in user_prompt:
            on_delta("Yes — allowlist.")
            return llm_result("Yes — allowlist.")
        await asyncio.sleep(30)  # the slow local model the cancel button exists for
        return llm_result("too late")

    monkeypatch.setattr(llm_service, "stream", stream)

    async def collect_until_first_done():
        with SessionLocal() as db:
            row = db.get(CodeReview, review["id"])
            assert row is not None
            prepared = discussion.prepare_discussion(
                db,
                row,
                [
                    DiscussThread(thread_id=thread_ids[0], message="Can we use an allowlist?"),
                    DiscussThread(thread_id=thread_ids[1], message="Is the log line necessary?"),
                ],
            )
        streamer = cast("AsyncGenerator[dict]", discussion.stream_discussion(prepared))
        events = []
        async for event in streamer:
            events.append(event)
            if event["type"] == "thread_done":
                await streamer.aclose()  # what the client abort does to the generator
                break
        pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        return events, pending

    events, pending = asyncio.run(collect_until_first_done())

    assert [event["type"] for event in events][-1] == "thread_done"
    assert pending == []

    stored = client.get(f"/api/reviews/{review['id']}").json()
    threads = {thread["id"]: thread for thread in stored["threads"]}
    assert [message["role"] for message in threads[thread_ids[0]]["messages"]] == [
        "assistant",
        "user",
        "assistant",
    ]
    assert [message["role"] for message in threads[thread_ids[1]]["messages"]] == ["assistant"]


def test_stream_unknown_review_is_404(client):
    response = client.post(
        "/api/reviews/999999/discuss/stream",
        json={"threads": [{"thread_id": 1, "message": "hello"}]},
    )
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_stream_foreign_thread_is_rejected_before_streaming(client, monkeypatch):
    first = seed_review(client, monkeypatch)
    second = seed_review(client, monkeypatch)

    response = client.post(
        f"/api/reviews/{first['id']}/discuss/stream",
        json={"threads": [{"thread_id": second["threads"][0]["id"], "message": "hijack"}]},
    )
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
    assert "does not belong" in response.json()["detail"]
