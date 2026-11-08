from __future__ import annotations

import inspect
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.config import get_settings
from app.db.base import utcnow
from app.db.session import SessionLocal
from app.models.review import CodeReview, ReviewStatus
from app.models.user import User
from app.services.progress import bus
from tests.fixtures import PR_URL, provision


@pytest.fixture()
def serverless(monkeypatch):
    """Run one test with SERVERLESS=true; `get_settings` is cached, so clear it both ways."""
    monkeypatch.setenv("SERVERLESS", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _owner_id() -> int:
    db = SessionLocal()
    try:
        owner = db.scalars(select(User)).first()
        assert owner is not None
        return owner.id
    finally:
        db.close()


def test_sign_up_can_be_disabled(client, monkeypatch, serverless):
    monkeypatch.setenv("SIGNUP_ENABLED", "false")
    get_settings.cache_clear()

    response = client.post(
        "/api/auth/signup",
        json={"email": "late@example.com", "password": "correct-horse-battery"},
    )
    assert response.status_code == 403
    assert "Sign-up is disabled" in response.json()["detail"]


def test_skills_are_read_only_and_listed_without_write_actions(client, serverless):
    listing = client.get("/api/skills").json()
    assert listing["uploads_enabled"] is False
    assert any(foundation["id"] == "code-review" for foundation in listing["foundations"])

    upload = client.post(
        "/api/skills/files",
        files={"file": ("rules.md", b"# Rules", "text/markdown")},
    )
    assert upload.status_code == 403
    assert "read-only" in upload.json()["detail"]

    created = client.post("/api/skills/foundations", data={"name": "blocked"}, files=[])
    assert created.status_code == 403

    deleted = client.delete("/api/skills/foundations/anything")
    assert deleted.status_code == 403


def test_local_ollama_is_hidden_and_rejected(client, serverless):
    provision(client)

    catalog = client.get("/api/models").json()
    assert all(not model["id"].startswith("ollama-local:") for model in catalog["models"])

    response = client.post(
        "/api/reviews", json={"pr_url": PR_URL, "model": "ollama-local:llama3"}
    )
    assert response.status_code == 422
    assert "not available on this deployment" in response.json()["detail"]


def test_ingest_is_a_background_task_in_serverless_mode(serverless):
    from app.services.review_pipeline import schedule_ingest

    scheduled: list[tuple[object, tuple, dict]] = []

    class FakeBackground:
        def add_task(self, func, *args, **kwargs):
            scheduled.append((func, args, kwargs))

    schedule_ingest(424242, FakeBackground())

    assert len(scheduled) == 1
    func, args, _ = scheduled[0]
    assert getattr(func, "__name__", "") == "run_ingest"
    assert inspect.iscoroutinefunction(func)
    assert args == (424242,)


def test_a_stale_running_review_is_failed_on_read_and_announced(client):
    owner = _owner_id()
    db = SessionLocal()
    try:
        stale = CodeReview(
            user_id=owner, pr_url=PR_URL, status=ReviewStatus.RUNNING, model_used="ollama-local:llama3"
        )
        fresh = CodeReview(
            user_id=owner, pr_url=PR_URL, status=ReviewStatus.RUNNING, model_used="ollama-local:llama3"
        )
        db.add_all([stale, fresh])
        db.commit()
        stale_id, fresh_id = stale.id, fresh.id
        db.execute(
            update(CodeReview)
            .where(CodeReview.id == stale_id)
            .values(updated_at=utcnow() - timedelta(minutes=30))
        )
        db.commit()
    finally:
        db.close()

    bus.reset()
    assert client.get(f"/api/reviews/{stale_id}").json()["status"] == "failed"
    assert client.get(f"/api/reviews/{fresh_id}").json()["status"] == "running"

    events = bus.history(stale_id)
    assert events and events[-1].stage == "error" and events[-1].terminal is True
