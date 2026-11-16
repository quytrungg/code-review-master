"""Standing review policies: matching, the per-PR claim, `max_active`, ownership and failures."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db.base import utcnow
from app.db.session import SessionLocal
from app.models.cached_pr import CachedPR, InboxInvolvement, InboxStatus
from app.models.review import CodeReview, ReviewStatus
from app.models.watch import ReviewTrigger
from app.services import policy_service, watch_service
from tests.conftest import TEST_EMAIL, wait_for_review
from tests.fixtures import PR_URL, provision


def _user_id(email: str = TEST_EMAIL) -> int:
    with SessionLocal() as db:
        return db.execute(text("SELECT id FROM users WHERE email = :email"), {"email": email}).scalar_one()


def _seed_pr(
    *,
    owner: str = "octo",
    name: str = "example",
    number: int = 123,
    involvement: str = InboxInvolvement.REVIEWER,
    status: str = InboxStatus.NEEDS_REVIEW,
    linked_review_id: int | None = None,
    url: str | None = None,
) -> int:
    with SessionLocal() as db:
        row = CachedPR(
            user_id=_user_id(),
            github_pr_id=9000 + number,
            repo_owner=owner,
            repo_name=name,
            pr_number=number,
            pr_url=url or f"https://github.com/{owner}/{name}/pull/{number}",
            title="A change",
            author_username="bob",
            status=status,
            involvement=involvement,
            last_github_activity_at=utcnow(),
            linked_review_id=linked_review_id,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id


def _policy(client, **overrides) -> dict:
    payload = {
        "repo_pattern": "octo/example",
        "involvement": "reviewer",
        "model": "ollama-local:llama3",
        "skill_foundation": "code-review",
        "max_active": 1,
        "enabled": True,
    }
    payload.update(overrides)
    response = client.post("/api/policies", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _stub_ingest(monkeypatch, *, fail: str | None = None):
    calls: list[int] = []

    async def fake_ingest(review_id: int, **_kwargs):
        calls.append(review_id)
        if fail:
            return
        with SessionLocal() as db:
            review = db.get(CodeReview, review_id)
            review.status = ReviewStatus.DRAFT
            db.commit()

    monkeypatch.setattr("app.services.review_pipeline.run_ingest", fake_ingest)
    return calls


def test_matching_cached_pr_starts_one_linked_policy_review(client, monkeypatch):
    provision(client)
    cached_id = _seed_pr()
    policy = _policy(client)
    calls = _stub_ingest(monkeypatch)

    outcome = asyncio.run(watch_service.tick())

    assert len(outcome.policy_started) == 1
    review_id = outcome.policy_started[0]
    assert calls == [review_id]

    listing = client.get("/api/reviews").json()
    assert len(listing) == 1
    assert listing[0]["id"] == review_id
    assert listing[0]["trigger"] == ReviewTrigger.POLICY

    with SessionLocal() as db:
        review = db.get(CodeReview, review_id)
        assert review.policy_id == policy["id"]
        row = db.get(CachedPR, cached_id)
        assert row.linked_review_id == review_id


def test_a_second_tick_starts_nothing(client, monkeypatch):
    provision(client)
    _seed_pr()
    _policy(client)
    _stub_ingest(monkeypatch)

    first = asyncio.run(watch_service.tick())
    second = asyncio.run(watch_service.tick())

    assert len(first.policy_started) == 1
    assert second.policy_started == []
    assert second.policy_skipped == 0
    assert len(client.get("/api/reviews").json()) == 1


def test_non_matching_repo_starts_nothing(client, monkeypatch):
    provision(client)
    _seed_pr(owner="other", name="lib", number=5)
    _policy(client)
    _stub_ingest(monkeypatch)

    outcome = asyncio.run(watch_service.tick())
    assert outcome.policy_started == []
    assert client.get("/api/reviews").json() == []


def test_linked_and_non_queue_rows_are_untouched(client, monkeypatch):
    provision(client)
    with SessionLocal() as db:
        existing = CodeReview(
            user_id=_user_id(), pr_url=PR_URL, vcs="github",
            model_used="ollama-local:llama3", status=ReviewStatus.DRAFT,
        )
        db.add(existing)
        db.commit()
        existing_id = existing.id

    _seed_pr(number=123, linked_review_id=existing_id)
    _seed_pr(number=124, status=InboxStatus.APPROVED)
    _policy(client)
    _stub_ingest(monkeypatch)

    outcome = asyncio.run(watch_service.tick())
    assert outcome.policy_started == []
    assert len(client.get("/api/reviews").json()) == 1


def test_involvement_filter_is_applied(client, monkeypatch):
    provision(client)
    _seed_pr(involvement=InboxInvolvement.AUTHOR)
    _policy(client, involvement="reviewer")
    _stub_ingest(monkeypatch)

    assert asyncio.run(watch_service.tick()).policy_started == []

    _policy(client, involvement="any")
    outcome = asyncio.run(watch_service.tick())
    assert len(outcome.policy_started) == 1


def test_max_active_one_queues_the_second_pr(client, monkeypatch):
    provision(client)
    _seed_pr(number=123)
    _seed_pr(number=124)
    policy = _policy(client, max_active=1)
    _stub_ingest(monkeypatch)

    first = asyncio.run(watch_service.tick())
    assert len(first.policy_started) == 1
    assert first.policy_skipped == 1

    # The first review is `draft`, which counts against max_active, so the second PR waits.
    second = asyncio.run(watch_service.tick())
    assert second.policy_started == []

    first_id = first.policy_started[0]
    with SessionLocal() as db:
        db.get(CodeReview, first_id).status = ReviewStatus.APPLIED
        db.commit()

    third = asyncio.run(watch_service.tick())
    assert len(third.policy_started) == 1
    assert third.policy_started[0] != first_id

    with SessionLocal() as db:
        second_review = db.get(CodeReview, third.policy_started[0])
        assert second_review.policy_id == policy["id"]


def test_disabled_policy_is_not_evaluated(client, monkeypatch):
    provision(client)
    _seed_pr()
    _policy(client, enabled=False)
    _stub_ingest(monkeypatch)

    assert asyncio.run(watch_service.tick()).policy_started == []
    assert client.get("/api/reviews").json() == []


def test_failed_creation_releases_the_claim_and_records_the_error(client, monkeypatch):
    from app.services.review_pipeline import PipelineError

    provision(client)
    cached_id = _seed_pr()
    policy = _policy(client)
    _stub_ingest(monkeypatch)

    def boom(*args, **kwargs):
        raise PipelineError("No active model key for this provider.", 400)
    monkeypatch.setattr("app.services.review_pipeline.create_running_review", boom)

    outcome = asyncio.run(watch_service.tick())

    assert outcome.policy_started == []
    assert outcome.policy_failed and outcome.policy_failed[0]["policy_id"] == policy["id"]
    with SessionLocal() as db:
        assert db.get(CachedPR, cached_id).policy_claim_at is None
        assert "No active model key" in (db.get(policy_service.ReviewPolicy, policy["id"]).last_error or "")


def test_ownership_is_a_404_for_another_account(client, second_client, monkeypatch):
    provision(client)
    provision(second_client)
    other = _policy(second_client, repo_pattern="other/lib")

    assert client.patch(f"/api/policies/{other['id']}", json={"enabled": False}).status_code == 404
    assert client.delete(f"/api/policies/{other['id']}").status_code == 404


def test_crud_and_validation(client):
    provision(client)
    policy = _policy(client, repo_pattern="octo/*")
    assert policy["repo_pattern"] == "octo/*"

    updated = client.patch(
        f"/api/policies/{policy['id']}",
        json={"max_active": 3, "enabled": False, "involvement": "any"},
    )
    assert updated.status_code == 200
    assert updated.json()["max_active"] == 3
    assert updated.json()["enabled"] is False
    assert updated.json()["involvement"] == "any"

    assert client.post(
        "/api/policies",
        json={"repo_pattern": "octo/example", "model": "gpt-4"},
    ).status_code == 422
    assert client.post(
        "/api/policies",
        json={"repo_pattern": "octo/example", "model": "ollama-local:llama3", "involvement": "owner"},
    ).status_code == 422
    assert client.post(
        "/api/policies",
        json={"repo_pattern": "octo/example", "model": "ollama-local:llama3", "skill_foundation": "missing"},
    ).status_code == 422

    assert client.delete(f"/api/policies/{policy['id']}").status_code == 204
    assert client.get("/api/policies").json() == []


def test_tick_endpoint_reports_policy_results(client, monkeypatch):
    from app.core.config import get_settings

    provision(client)
    _seed_pr()
    _policy(client)
    _stub_ingest(monkeypatch)
    monkeypatch.setattr(get_settings(), "watch_tick_secret", "s3cret")

    response = client.post("/api/watches/tick", headers={"x-watch-secret": "s3cret"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["policy_started"]) == 1
    review_id = body["policy_started"][0]
    assert wait_for_review(client, review_id)["status"] != "running"
