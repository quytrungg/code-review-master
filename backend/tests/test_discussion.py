from __future__ import annotations

import json

from app.services import llm_service
from tests.fixtures import PR_URL, as_result, provision
from tests.test_review_pipeline import FINDINGS, configure

TOKEN = "ghp_test_token_123456"


def seed_review(client, monkeypatch) -> dict:
    from tests.conftest import start_review

    configure(monkeypatch, json.dumps(FINDINGS))
    provision(client)
    return start_review(client, PR_URL, "ollama-local:llama3")


def test_batch_discussion_adds_user_and_assistant_messages(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    thread_ids = [thread["id"] for thread in review["threads"]]

    async def reply(settings_row, model, system_prompt, user_prompt, **kwargs):
        if "Review state" in user_prompt:  # the verdict pass
            return json.dumps({"verdict": "APPROVE", "confidence": 91, "rationale": "All resolved."})
        assert "Review standards" in system_prompt
        assert "Conversation so far" in user_prompt
        assert "Reviewer (user)" in user_prompt
        return "You are right — an allowlist is safer here."

    monkeypatch.setattr(llm_service, "generate", as_result(reply))

    response = client.post(
        f"/api/reviews/{review['id']}/discuss",
        json={
            "threads": [
                {"thread_id": thread_ids[0], "message": "Can we use an allowlist?"},
                {"thread_id": thread_ids[1], "message": "Is the log line necessary?"},
            ]
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert [result["ok"] for result in body["results"]] == [True, True]
    assert body["review"]["status"] == "in_discussion"

    threads = {thread["id"]: thread for thread in body["review"]["threads"]}
    first = threads[thread_ids[0]]["messages"]
    assert [message["role"] for message in first] == ["assistant", "user", "assistant"]
    assert first[1]["content"] == "Can we use an allowlist?"
    assert first[2]["content"].startswith("You are right")

    # Persisted, not just echoed.
    stored = client.get(f"/api/reviews/{review['id']}").json()
    assert len(stored["threads"][0]["messages"]) == 3


def test_partial_failure_keeps_the_successful_reply(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    thread_ids = [thread["id"] for thread in review["threads"]]
    calls = {"count": 0}

    async def flaky(settings_row, model, system_prompt, user_prompt, **kwargs):
        calls["count"] += 1
        if "Is the log line" in user_prompt:
            raise llm_service.LLMError("Ollama does not have the model 'nope'.")
        return "Fixed answer."

    monkeypatch.setattr(llm_service, "generate", as_result(flaky))

    response = client.post(
        f"/api/reviews/{review['id']}/discuss",
        json={
            "threads": [
                {"thread_id": thread_ids[0], "message": "Why?"},
                {"thread_id": thread_ids[1], "message": "Is the log line necessary?"},
            ]
        },
    )
    assert response.status_code == 200
    body = response.json()
    results = {result["thread_id"]: result for result in body["results"]}
    assert results[thread_ids[0]]["ok"] is True
    assert results[thread_ids[1]]["ok"] is False
    assert "nope" in results[thread_ids[1]]["error"]

    threads = {thread["id"]: thread for thread in body["review"]["threads"]}
    # The failed thread still keeps the reviewer's message.
    assert [message["role"] for message in threads[thread_ids[1]]["messages"]] == [
        "assistant",
        "user",
    ]


def test_foreign_thread_id_is_rejected(client, monkeypatch):
    first = seed_review(client, monkeypatch)
    second = seed_review(client, monkeypatch)

    async def reply(settings_row, model, system_prompt, user_prompt, **kwargs):
        return "ok"

    monkeypatch.setattr(llm_service, "generate", as_result(reply))

    response = client.post(
        f"/api/reviews/{first['id']}/discuss",
        json={"threads": [{"thread_id": second["threads"][0]["id"], "message": "hijack"}]},
    )
    assert response.status_code == 400
    assert "does not belong" in response.json()["detail"]


def test_empty_batch_is_422(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    response = client.post(f"/api/reviews/{review['id']}/discuss", json={"threads": []})
    assert response.status_code == 422


def test_unknown_review_is_404(client):
    response = client.post(
        "/api/reviews/999999/discuss",
        json={"threads": [{"thread_id": 1, "message": "hello"}]},
    )
    assert response.status_code == 404


def test_discussion_survives_model_failure_and_keeps_status_draft(client, monkeypatch):
    review = seed_review(client, monkeypatch)

    async def boom(settings_row, model, system_prompt, user_prompt, **kwargs):
        raise llm_service.LLMError("connection refused")

    monkeypatch.setattr(llm_service, "generate", as_result(boom))

    response = client.post(
        f"/api/reviews/{review['id']}/discuss",
        json={"threads": [{"thread_id": review["threads"][0]["id"], "message": "still there?"}]},
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["ok"] is False
    assert response.json()["review"]["status"] == "draft"
