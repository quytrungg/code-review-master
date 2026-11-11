"""Push-back lessons (initiative 6, phase 36): the beta-gated draft + apply endpoints."""

from __future__ import annotations

import json

import pytest

from app.core.config import get_settings
from app.services import llm_service
from tests.conftest import start_review
from tests.fixtures import as_result, provision
from tests.test_review_pipeline import FINDINGS, configure

PR_URL = "https://github.com/octo/example/pull/123"


def seed_review(client, monkeypatch) -> dict:
    configure(monkeypatch, json.dumps(FINDINGS))
    provision(client)
    return start_review(client, PR_URL, "ollama-local:llama3")


def enable_lessons(client) -> None:
    response = client.put("/api/settings", json={"beta_features": {"push_back_lessons": True}})
    assert response.status_code == 200, response.text


def first_ai_thread(review: dict) -> dict:
    return next(thread for thread in review["threads"] if thread["origin"] == "AI_GENERATED")


def test_lesson_endpoints_are_off_without_the_beta_flag(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    thread = first_ai_thread(review)

    draft = client.post(f"/api/reviews/{review['id']}/threads/{thread['id']}/lesson/draft")
    assert draft.status_code == 422, draft.text
    assert "Settings" in draft.json()["detail"]

    applied = client.post(
        f"/api/reviews/{review['id']}/threads/{thread['id']}/lesson",
        json={"foundation_id": "code-review", "title": "T", "body": "B"},
    )
    assert applied.status_code == 422, applied.text


def test_draft_returns_an_editable_rule_from_the_review_model(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    enable_lessons(client)
    thread = first_ai_thread(review)

    seen: dict = {}

    def generate(credentials, model, system_prompt, user_prompt, **kwargs):
        seen["purpose"] = kwargs.get("purpose")
        seen["thread_id"] = kwargs.get("thread_id")
        seen["user_prompt"] = user_prompt
        return json.dumps(
            {
                "title": "Verify limit is validated before flagging unbounded queries",
                "body": "Applies to: *.py query builders. Check the caller passes a bounded limit.",
            }
        )

    monkeypatch.setattr(llm_service, "generate", as_result(generate))

    response = client.post(f"/api/reviews/{review['id']}/threads/{thread['id']}/lesson/draft")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"].startswith("Verify limit")
    assert body["body"].startswith("Applies to:")
    assert seen["purpose"] == "lesson"
    assert seen["thread_id"] == thread["id"]
    assert "src/services/auth.py" in seen["user_prompt"]


def test_draft_failure_is_a_friendly_error_not_a_crash(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    enable_lessons(client)
    thread = first_ai_thread(review)

    def generate(*args, **kwargs):
        raise llm_service.LLMError("provider down")

    monkeypatch.setattr(llm_service, "generate", generate)

    response = client.post(f"/api/reviews/{review['id']}/threads/{thread['id']}/lesson/draft")
    assert response.status_code == 502, response.text
    assert "Push back anyway" in response.json()["detail"]


def test_apply_writes_the_lesson_file_and_attribution(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    enable_lessons(client)
    thread = first_ai_thread(review)

    response = client.post(
        f"/api/reviews/{review['id']}/threads/{thread['id']}/lesson",
        json={
            "foundation_id": "code-review",
            "title": "Unbounded query: check the caller first",
            "body": "Applies to: *.py. Verify the caller passes a validated limit before flagging.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["foundation"] == "code-review"
    assert body["lesson_id"] > 0
    # The filetype token is what makes skill_loader select the file for future .py reviews.
    assert body["path"] == "lessons/py-unbounded-query-check-the-caller-first.md"

    root = get_settings().resolved_skills_dir
    text = (root / body["path"]).read_text(encoding="utf-8")
    assert "Unbounded query: check the caller first" in text
    assert "Applies to: *.py" in text
    assert f"review #{review['id']}" in text and f"thread #{thread['id']}" in text

    # The next review of the same file type loads the lesson into its prompt.
    from app.services import skill_loader

    bundle = skill_loader.load_bundle({"py"}, root=root)
    assert "Unbounded query: check the caller first" in bundle.text

    # The default foundation is session-scoped and other tests assert on its file list.
    (root / body["path"]).unlink()


def test_apply_rejects_blank_text_and_unknown_foundations(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    enable_lessons(client)
    thread = first_ai_thread(review)
    url = f"/api/reviews/{review['id']}/threads/{thread['id']}/lesson"

    blank = client.post(url, json={"foundation_id": "code-review", "title": "  ", "body": "B"})
    assert blank.status_code == 422, blank.text

    unknown = client.post(
        url, json={"foundation_id": "does-not-exist", "title": "T", "body": "B"}
    )
    assert unknown.status_code == 404, unknown.text


def test_thread_must_belong_to_the_review(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    enable_lessons(client)

    response = client.post(f"/api/reviews/{review['id']}/threads/999999/lesson/draft")
    assert response.status_code == 404, response.text


def test_another_accounts_thread_is_a_404(client, second_client, monkeypatch):
    review = seed_review(client, monkeypatch)
    enable_lessons(client)
    thread = first_ai_thread(review)

    for path in (
        f"/api/reviews/{review['id']}/threads/{thread['id']}/lesson/draft",
        f"/api/reviews/{review['id']}/threads/{thread['id']}/lesson",
    ):
        response = second_client.post(path, json={"foundation_id": "code-review", "title": "T", "body": "B"})
        assert response.status_code == 404, (path, response.text)


@pytest.mark.parametrize("endpoint", ["draft", ""])
def test_lesson_endpoints_after_disable(client, monkeypatch, endpoint):
    """Turning the flag back off closes the endpoints again — the gate is read per request."""
    review = seed_review(client, monkeypatch)
    enable_lessons(client)
    thread = first_ai_thread(review)
    disabled = client.put("/api/settings", json={"beta_features": {"push_back_lessons": False}})
    assert disabled.status_code == 200, disabled.text

    suffix = "draft" if endpoint == "draft" else ""
    url = f"/api/reviews/{review['id']}/threads/{thread['id']}/lesson"
    if suffix:
        url = f"{url}/{suffix}"
    payload = None if endpoint == "draft" else {"foundation_id": "code-review", "title": "T", "body": "B"}
    response = client.post(url, json=payload) if payload else client.post(url)
    assert response.status_code == 422, response.text
