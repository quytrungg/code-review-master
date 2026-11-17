"""A finished review is a notification until the operator opens it."""

from __future__ import annotations

import json

from tests.conftest import start_review
from tests.fixtures import PR_URL, provision
from tests.test_review_pipeline import FINDINGS, configure


def _review_list(client) -> list[dict]:
    response = client.get("/api/reviews")
    assert response.status_code == 200, response.text
    return response.json()


def _notification_count(client) -> int:
    response = client.get("/api/reviews/notifications")
    assert response.status_code == 200, response.text
    return response.json()["unread_count"]


def test_a_finished_review_is_unread_until_it_is_opened(client, monkeypatch):
    configure(monkeypatch, json.dumps(FINDINGS))
    provision(client)
    review = start_review(client, PR_URL, "ollama-local:llama3")

    row = _review_list(client)[0]
    assert row["has_unread"] is True
    assert _notification_count(client) == 1

    seen = client.post(f"/api/reviews/{review['id']}/seen")
    assert seen.status_code == 200, seen.text
    assert seen.json()["has_unread"] is False
    assert _notification_count(client) == 0
    assert _review_list(client)[0]["has_unread"] is False


def test_acknowledging_twice_keeps_the_first_timestamp(client, monkeypatch):
    configure(monkeypatch, json.dumps(FINDINGS))
    provision(client)
    review = start_review(client, PR_URL, "ollama-local:llama3")

    assert client.post(f"/api/reviews/{review['id']}/seen").status_code == 200

    from app.db.session import SessionLocal
    from app.models.review import CodeReview

    db = SessionLocal()
    try:
        first = db.get(CodeReview, review["id"]).completed_seen_at
    finally:
        db.close()
    assert first is not None

    assert client.post(f"/api/reviews/{review['id']}/seen").status_code == 200
    db = SessionLocal()
    try:
        assert db.get(CodeReview, review["id"]).completed_seen_at == first
    finally:
        db.close()
    assert _notification_count(client) == 0


def test_a_running_review_is_not_a_notification(client, monkeypatch):
    """Opening the workspace early must not swallow the notification the job will produce."""
    configure(monkeypatch, json.dumps(FINDINGS))
    provision(client)
    # The job is scheduled by the route; dropping the scheduler keeps the row `running` long
    # enough to prove the rule, without stubbing the pipeline itself.
    monkeypatch.setattr("app.api.routes.reviews.schedule_ingest", lambda *args, **kwargs: None)

    created = client.post(
        "/api/reviews", json={"pr_url": PR_URL, "model": "ollama-local:llama3"}
    )
    assert created.status_code == 202, created.text
    review_id = created.json()["id"]

    row = _review_list(client)[0]
    assert row["status"] == "running"
    assert row["has_unread"] is False
    assert _notification_count(client) == 0
    assert client.post(f"/api/reviews/{review_id}/seen").json()["has_unread"] is False

    # It finishes now: the early visit did not mark it seen.
    from app.db.session import SessionLocal
    from app.models.review import CodeReview, ReviewStatus

    db = SessionLocal()
    try:
        db.get(CodeReview, review_id).status = ReviewStatus.DRAFT
        db.commit()
    finally:
        db.close()

    assert _review_list(client)[0]["has_unread"] is True
    assert _notification_count(client) == 1
