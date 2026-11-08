from __future__ import annotations

import json

from app.db.session import SessionLocal
from app.models.review import CodeReview, ReviewStatus
from app.services.progress import bus
from tests.conftest import wait_for_review
from tests.fixtures import PR_URL, provision
from tests.test_review_pipeline import FINDINGS, configure


def _read_sse(client, review_id: int, max_events: int = 40) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    with client.stream("GET", f"/api/reviews/{review_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        event_name = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                event_name = line[len("event: ") :]
            elif line.startswith("data: "):
                events.append((event_name or "message", json.loads(line[len("data: ") :])))
                event_name = None
                if len(events) >= max_events:
                    break
                if events[-1][0] in ("done", "failed"):
                    break
    return events


def test_review_creation_returns_202_and_streams_every_stage(client, monkeypatch):
    configure(monkeypatch, json.dumps(FINDINGS))
    provision(client)

    accepted = client.post(
        "/api/reviews", json={"pr_url": PR_URL, "model": "ollama-local:llama3"}
    )
    assert accepted.status_code == 202
    body = accepted.json()
    assert body["status"] == "running"
    assert body["skill_foundation"] == "code-review"

    review_id = body["id"]
    events = _read_sse(client, review_id)
    names = [name for name, _ in events]
    assert names[-1] == "done"
    stages = [payload["stage"] for name, payload in events if name == "progress"]
    for expected in ("queued", "fetch_pr", "fetch_diff", "parse_diff", "skills", "model", "anchor"):
        assert expected in stages, f"missing stage {expected} in {stages}"

    final = events[-1][1]
    assert final["data"]["thread_count"] == 2
    assert final["progress"] == 100

    stored = client.get(f"/api/reviews/{review_id}").json()
    assert stored["status"] == "draft"


def test_events_replay_for_a_late_subscriber(client, monkeypatch):
    configure(monkeypatch, json.dumps(FINDINGS))
    provision(client)
    review_id = client.post(
        "/api/reviews", json={"pr_url": PR_URL, "model": "ollama-local:llama3"}
    ).json()["id"]
    wait_for_review(client, review_id)

    events = _read_sse(client, review_id)
    assert events, "history should be replayed to a subscriber that connects after the job"
    assert events[-1][0] == "done"
    assert events[0][1]["stage"] == "queued"


def test_failed_job_streams_an_error_event(client, monkeypatch):
    configure(monkeypatch, "not json at all")
    provision(client)
    review_id = client.post(
        "/api/reviews", json={"pr_url": PR_URL, "model": "ollama-local:llama3"}
    ).json()["id"]

    events = _read_sse(client, review_id)
    assert events[-1][0] == "failed"
    assert "no parsable JSON" in events[-1][1]["detail"]

    stored = client.get(f"/api/reviews/{review_id}").json()
    assert stored["status"] == "failed"


def test_events_for_unknown_review_is_404(client):
    response = client.get("/api/reviews/999999/events")
    assert response.status_code == 404


def test_orphaned_running_reviews_are_failed_on_startup(client):
    from sqlalchemy import select

    from app.db.init_db import fail_orphaned_reviews
    from app.models.user import User

    db = SessionLocal()
    try:
        owner = db.scalars(select(User)).first()
        assert owner is not None
        review = CodeReview(
            user_id=owner.id,
            pr_url=PR_URL,
            status=ReviewStatus.RUNNING,
            model_used="ollama-local:llama3",
        )
        db.add(review)
        db.commit()
        review_id = review.id
    finally:
        db.close()

    assert fail_orphaned_reviews() >= 1

    stored = client.get(f"/api/reviews/{review_id}").json()
    assert stored["status"] == "failed"
    assert "server restart" in stored["error"]


def test_progress_bus_replays_history_without_duplicates(client):
    from sqlalchemy import select

    from app.models.user import User

    db = SessionLocal()
    try:
        owner = db.scalars(select(User)).first()
        assert owner is not None
        review = CodeReview(
            user_id=owner.id,
            pr_url=PR_URL,
            status=ReviewStatus.DRAFT,
            model_used="ollama-local:llama3",
        )
        db.add(review)
        db.commit()
        review_id = review.id
    finally:
        db.close()

    bus.reset()
    bus.publish(review_id, "queued", "Queued")
    bus.publish(review_id, "done", "Done", terminal=True)
    history = bus.history(review_id)
    assert [event.seq for event in history] == [1, 2]
    assert bus.is_finished(review_id) is True


def test_progress_history_keeps_only_the_newest_events(client, monkeypatch):
    import app.services.progress as progress

    from sqlalchemy import select

    from app.models.user import User

    db = SessionLocal()
    try:
        owner = db.scalars(select(User)).first()
        assert owner is not None
        review = CodeReview(
            user_id=owner.id,
            pr_url=PR_URL,
            status=ReviewStatus.DRAFT,
            model_used="ollama-local:llama3",
        )
        db.add(review)
        db.commit()
        review_id = review.id
    finally:
        db.close()

    monkeypatch.setattr(progress, "MAX_EVENTS_PER_REVIEW", 5)
    for index in range(7):
        progress.bus.publish(review_id, "fetch_pr", f"step {index}")

    assert [event.seq for event in progress.bus.history(review_id)] == [3, 4, 5, 6, 7]
