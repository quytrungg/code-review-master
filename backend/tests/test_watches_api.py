"""The watch HTTP surface: CRUD, ownership, the idempotent create, and the secret-gated tick."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models.review import CodeReview, ReviewStatus
from app.services import watch_service
from tests.conftest import TEST_EMAIL
from tests.fixtures import PR_URL, provision


@pytest.fixture()
def serverless(monkeypatch):
    """Run one test with SERVERLESS=true; `get_settings` is cached, so clear it both ways."""
    monkeypatch.setenv("SERVERLESS", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def owner_id(email: str = TEST_EMAIL) -> int:
    with SessionLocal() as db:
        return int(
            db.execute(text("SELECT id FROM users WHERE email = :email"), {"email": email}).scalar_one()
        )


def make_review(commit: str = "aaa111", email: str = TEST_EMAIL) -> int:
    with SessionLocal() as db:
        review = CodeReview(
            user_id=owner_id(email),
            pr_url=PR_URL,
            vcs="github",
            pr_title="Charge customers",
            pr_number=123,
            repo_full_name="octo/example",
            commit_id=commit,
            model_used="ollama-local:llama3",
            skill_foundation="code-review",
            status=ReviewStatus.DRAFT,
        )
        db.add(review)
        db.commit()
        return review.id


def test_create_list_pause_and_delete_a_watch(client):
    provision(client)
    review_id = make_review()

    created = client.post("/api/watches", json={"review_id": review_id})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["pr_url"] == PR_URL
    assert body["vcs"] == "github"
    assert body["repo_full_name"] == "octo/example"
    assert body["pr_number"] == 123
    assert body["model_used"] == "ollama-local:llama3"
    assert body["skill_foundation"] == "code-review"
    assert body["last_seen_commit_id"] == "aaa111"
    assert body["last_review_id"] == review_id
    assert body["enabled"] is True

    listing = client.get("/api/watches").json()
    assert [row["id"] for row in listing] == [body["id"]]

    paused = client.patch(f"/api/watches/{body['id']}", json={"enabled": False})
    assert paused.status_code == 200, paused.text
    assert paused.json()["enabled"] is False

    deleted = client.delete(f"/api/watches/{body['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/watches").json() == []


def test_watching_the_same_pull_request_twice_returns_the_same_watch(client):
    provision(client)
    review_id = make_review()

    first = client.post("/api/watches", json={"review_id": review_id})
    second = client.post("/api/watches", json={"review_id": review_id})

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert len(client.get("/api/watches").json()) == 1


def test_pressing_watch_again_resumes_a_paused_watch(client):
    provision(client)
    review_id = make_review()
    watch_id = client.post("/api/watches", json={"review_id": review_id}).json()["id"]
    client.patch(f"/api/watches/{watch_id}", json={"enabled": False})

    resumed = client.post("/api/watches", json={"review_id": review_id})

    assert resumed.status_code == 200
    assert resumed.json()["enabled"] is True


def test_an_unknown_review_is_404(client):
    provision(client)
    response = client.post("/api/watches", json={"review_id": 999999})
    assert response.status_code == 404
    assert response.json()["detail"] == "Review not found"


def test_another_account_cannot_see_or_touch_a_watch(client, second_client):
    provision(client)
    review_id = make_review()
    watch_id = client.post("/api/watches", json={"review_id": review_id}).json()["id"]

    # The other account cannot watch a review it does not own, list the watch, or delete it.
    assert second_client.post("/api/watches", json={"review_id": review_id}).status_code == 404
    assert second_client.get("/api/watches").json() == []
    assert second_client.patch(f"/api/watches/{watch_id}", json={"enabled": False}).status_code == 404
    assert second_client.delete(f"/api/watches/{watch_id}").status_code == 404

    # And the first account's watch is untouched.
    assert client.get("/api/watches").json()[0]["enabled"] is True


def test_the_review_detail_and_list_expose_the_link(client):
    provision(client)
    review_id = make_review()
    watch_id = client.post("/api/watches", json={"review_id": review_id}).json()["id"]

    detail = client.get(f"/api/reviews/{review_id}").json()
    assert detail["watch"]["id"] == watch_id
    assert detail["parent_review_id"] is None
    assert detail["trigger"] is None

    # A delta review carries its parent and trigger, on the list row too.
    with SessionLocal() as db:
        delta = CodeReview(
            user_id=owner_id(),
            pr_url=PR_URL,
            vcs="github",
            status=ReviewStatus.DRAFT,
            commit_id="bbb222",
            watch_id=watch_id,
            parent_review_id=review_id,
            trigger="watch",
        )
        db.add(delta)
        db.commit()
        delta_id = delta.id

    rows = {row["id"]: row for row in client.get("/api/reviews").json()}
    assert rows[delta_id]["parent_review_id"] == review_id
    assert rows[delta_id]["trigger"] == "watch"
    assert client.get(f"/api/reviews/{delta_id}").json()["watch"]["id"] == watch_id


def test_the_tick_is_503_when_no_secret_is_configured(client, monkeypatch):
    monkeypatch.delenv("WATCH_TICK_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        response = client.post("/api/watches/tick")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 503
    assert "WATCH_TICK_SECRET" in response.json()["detail"]


def test_the_tick_rejects_a_missing_or_wrong_secret(client, monkeypatch):
    monkeypatch.setenv("WATCH_TICK_SECRET", "s3cret-value")
    get_settings.cache_clear()
    try:
        assert client.post("/api/watches/tick").status_code == 401
        assert client.post("/api/watches/tick", headers={"X-Watch-Secret": "nope"}).status_code == 401
        assert (
            client.post("/api/watches/tick", headers={"Authorization": "Bearer nope"}).status_code
            == 401
        )
    finally:
        monkeypatch.delenv("WATCH_TICK_SECRET")
        get_settings.cache_clear()


def test_the_tick_accepts_either_header(client, monkeypatch):
    monkeypatch.setenv("WATCH_TICK_SECRET", "s3cret-value")
    get_settings.cache_clear()
    try:
        via_header = client.post("/api/watches/tick", headers={"X-Watch-Secret": "s3cret-value"})
        via_bearer = client.post(
            "/api/watches/tick", headers={"Authorization": "Bearer s3cret-value"}
        )
    finally:
        monkeypatch.delenv("WATCH_TICK_SECRET")
        get_settings.cache_clear()

    assert via_header.status_code == 200, via_header.text
    assert via_bearer.status_code == 200, via_bearer.text
    assert via_header.json() == {
        "checked": 0,
        "unchanged": 0,
        "adopted": 0,
        "skipped": 0,
        "started": [],
        "failed": [],
    }


def test_the_tick_needs_no_session_cookie(client, monkeypatch):
    """A cron job has no cookie jar: the secret alone is enough."""
    monkeypatch.setenv("WATCH_TICK_SECRET", "s3cret-value")
    get_settings.cache_clear()
    try:
        with TestClient(app) as anonymous:
            response = anonymous.post(
                "/api/watches/tick", headers={"X-Watch-Secret": "s3cret-value"}
            )
    finally:
        monkeypatch.delenv("WATCH_TICK_SECRET")
        get_settings.cache_clear()

    assert response.status_code == 200, response.text
    # The CRUD surface still refuses a cookieless caller.
    assert anonymous.get("/api/watches").status_code in (401,)


def test_serverless_starts_no_watch_loop(client, serverless):
    before = watch_service.loop_task()
    with TestClient(app) as serverless_client:
        assert serverless_client.get("/api/health").status_code == 200
        assert watch_service.loop_task() is before


def test_a_local_lifespan_starts_and_stops_the_watch_loop(client):
    with TestClient(app) as local:
        task = watch_service.loop_task()
        assert task is not None and not task.done()
    assert watch_service.loop_task() is None


def test_start_loop_declines_when_the_interval_is_zero(client, monkeypatch):
    monkeypatch.setenv("WATCH_INTERVAL_MINUTES", "0")
    get_settings.cache_clear()
    try:
        assert watch_service.start_loop() is None
    finally:
        monkeypatch.delenv("WATCH_INTERVAL_MINUTES")
        get_settings.cache_clear()
