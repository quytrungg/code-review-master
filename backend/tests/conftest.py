from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

_TMP_DB = Path(tempfile.mkdtemp(prefix="acr-tests-")) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"

# Provider credentials are encrypted at rest, so every test run needs a key. Fixed, not a secret.
os.environ["CREDENTIALS_ENCRYPTION_KEY"] = "jViGHKfT9myHM70vzMgtTdVw7CsWitgWA-xXhDnLZLg="

# Keep uploads inside the test sandbox instead of writing into the repository.
_TMP_SKILLS = Path(tempfile.mkdtemp(prefix="acr-skills-"))
_TMP_FOUNDATIONS = Path(tempfile.mkdtemp(prefix="acr-foundations-"))
os.environ["SKILLS_DIR"] = str(_TMP_SKILLS)
os.environ["FOUNDATIONS_DIR"] = str(_TMP_FOUNDATIONS)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def seed_skill_tree() -> Path:
    """A small default foundation so tests never depend on the repository's library."""
    (_TMP_SKILLS / "references").mkdir(parents=True, exist_ok=True)
    (_TMP_SKILLS / "SKILL.md").write_text("# Test review standards\n\nEntry rules.", encoding="utf-8")
    (_TMP_SKILLS / "references" / "ruby.md").write_text("# Ruby rules\n\nBe careful.", encoding="utf-8")
    return _TMP_SKILLS


TEST_EMAIL = "tester@example.com"
TEST_PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="session")
def client():
    seed_skill_tree()
    # The client's lifespan runs `alembic upgrade head` against DATABASE_URL, so every
    # test exercises the real migration path rather than `create_all`.
    with TestClient(app) as test_client:
        # Everything under /api (except /api/auth/*) needs an account; the cookie stays in
        # this client's jar for the whole session.
        signup = test_client.post(
            "/api/auth/signup", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        assert signup.status_code == 201, signup.text
        yield test_client


@pytest.fixture()
def anon_client():
    """No session cookie: what an unauthenticated browser hits."""
    return TestClient(app)


@pytest.fixture()
def second_client():
    """A second account, for isolation tests."""
    with TestClient(app) as other:
        response = other.post(
            "/api/auth/signup", json={"email": "other@example.com", "password": TEST_PASSWORD}
        )
        assert response.status_code in (201, 409), response.text
        if response.status_code == 409:
            login = other.post(
                "/api/auth/login", json={"email": "other@example.com", "password": TEST_PASSWORD}
            )
            assert login.status_code == 200, login.text
        yield other


def wait_for_review(client, review_id: int, timeout: float = 15.0) -> dict:
    """Poll until the background ingest job leaves the `running` state."""
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/reviews/{review_id}").json()
        if body.get("status") != "running":
            return body
        time.sleep(0.05)
    raise AssertionError(f"Review {review_id} stayed running: {body}")


def start_review(client, pr_url: str, model: str, foundation: str | None = None, status: int = 202):
    payload = {"pr_url": pr_url, "model": model}
    if foundation is not None:
        payload["skill_foundation"] = foundation
    response = client.post("/api/reviews", json=payload)
    assert response.status_code == status, response.text
    if status != 202:
        return response
    return wait_for_review(client, response.json()["id"])


@pytest.fixture(autouse=True)
def reset_settings(client):
    from app.db.session import SessionLocal
    from app.models.review import CodeReview, ReviewThread, ThreadRound, ThreadMessage
    from app.models.settings import Settings
    from app.services.progress import bus

    db = SessionLocal()
    try:
        db.query(ThreadMessage).delete()
        db.query(ThreadRound).delete()
        db.query(ReviewThread).delete()
        db.query(CodeReview).delete()
        db.query(Settings).delete()
        db.commit()
    finally:
        db.close()
    bus.reset()
    yield
