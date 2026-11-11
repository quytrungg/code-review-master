"""Watching a PR: the claim, the no-op tick, the linked delta review, and its failure paths."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.models.review import CodeReview, ReviewStatus
from app.models.watch import ReviewTrigger, ReviewWatch
from app.services import github_service, llm_service, vcs, watch_service
from app.services.pull_request import PullRequestInfo
from tests.conftest import TEST_EMAIL
from tests.fixtures import PR_URL, llm_result, provision

HEAD_A = "aaa111"
HEAD_B = "bbb222"

# The delta between HEAD_A and HEAD_B: one new file change, nothing else.
DELTA_DIFF = """diff --git a/src/services/billing.py b/src/services/billing.py
--- a/src/services/billing.py
+++ b/src/services/billing.py
@@ -1,2 +1,3 @@ def charge():
+    total = compute_total()
     return total
"""

FINDINGS = [
    {
        "filePath": "src/services/billing.py",
        "lineNumber": 2,
        "diffHunk": "",
        "initialComment": "**High** — `compute_total` has no timeout; a hung provider blocks the worker.",
    }
]


class GitHub:
    """A stub provider whose head and comparison the test controls."""

    def __init__(self, head: str = HEAD_A, diff: str = DELTA_DIFF, *, fail_compare: bool = False):
        self.head = head
        self.diff = diff
        self.fail_compare = fail_compare
        self.fetches = 0
        self.compares: list[tuple[str, str]] = []
        self.before_fetch: Callable[[], None] | None = None  # hook: called at fetch_pr start

    async def fetch_pr(self, token, owner, repo, number, base_url=None):
        if self.before_fetch is not None:
            self.before_fetch()
        self.fetches += 1
        return PullRequestInfo(
            vcs="github",
            project=f"{owner}/{repo}",
            number=number,
            title="Charge customers",
            state="open",
            draft=False,
            head_sha=self.head,
            base_sha="base111",
            start_sha="base111",
            base_ref="main",
            html_url=PR_URL,
            author="octocat",
            body="Adds a total.",
            additions=1,
            deletions=0,
            changed_files=1,
        )

    async def compare(self, token, owner, repo, base, head, base_url=None):
        self.compares.append((base, head))
        if self.fail_compare:
            raise vcs.VCSError("GitHub cannot compare those commits — the branch was force-pushed.")
        return self.diff

    async def fetch_comments(self, token, repo_full_name, number, base_url=None):
        return []


def configure(monkeypatch, github: GitHub) -> GitHub:
    async def no_full_diff(token, owner, repo, number, base_url=None):
        raise AssertionError("a delta review must not refetch the whole diff")

    async def generate(*args, **kwargs):
        return llm_result(
            json.dumps({"verdict": "COMMENT", "confidence": 62, "findings": FINDINGS})
        )

    monkeypatch.setattr(github_service, "fetch_pr", github.fetch_pr)
    monkeypatch.setattr(github_service, "compare", github.compare)
    monkeypatch.setattr(github_service, "fetch_review_comments", github.fetch_comments)
    monkeypatch.setattr(github_service, "fetch_diff", no_full_diff)
    monkeypatch.setattr(llm_service, "generate", generate)
    return github


def owner_id() -> int:
    with SessionLocal() as db:
        return int(
            db.execute(
                text("SELECT id FROM users WHERE email = :email"), {"email": TEST_EMAIL}
            ).scalar_one()
        )


def make_review(commit: str | None = HEAD_A) -> int:
    """A review row to watch, without running ingest for it."""
    with SessionLocal() as db:
        review = CodeReview(
            user_id=owner_id(),
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


def watch(review_id: int) -> int:
    with SessionLocal() as db:
        review = db.get(CodeReview, review_id)
        assert review is not None
        created, _ = watch_service.create_watch(db, review.user_id, review)
        return created.id


def reload_watch(watch_id: int) -> ReviewWatch:
    with SessionLocal() as db:
        row = db.get(ReviewWatch, watch_id)
        assert row is not None
        return row


def delta_reviews(watch_id: int) -> list[CodeReview]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(CodeReview).where(CodeReview.watch_id == watch_id).order_by(CodeReview.id)
            )
        )


def test_create_watch_copies_the_review_and_is_idempotent(client, monkeypatch):
    configure(monkeypatch, GitHub())
    provision(client)
    review_id = make_review()

    with SessionLocal() as db:
        review = db.get(CodeReview, review_id)
        assert review is not None
        row, created = watch_service.create_watch(db, review.user_id, review)

    assert created is True
    assert row.pr_url == PR_URL
    assert row.vcs == "github"
    assert row.repo_full_name == "octo/example"
    assert row.pr_number == 123
    assert row.model_used == "ollama-local:llama3"
    assert row.skill_foundation == "code-review"
    assert row.last_seen_commit_id == HEAD_A
    assert row.last_review_id == review_id
    assert row.enabled is True

    with SessionLocal() as db:
        stored = db.get(CodeReview, review_id)
        assert stored is not None
        again, created_again = watch_service.create_watch(db, row.user_id, stored)
    assert created_again is False
    assert again.id == row.id


def test_a_tick_with_an_unchanged_head_creates_nothing(client, monkeypatch):
    github = configure(monkeypatch, GitHub(head=HEAD_A))
    provision(client)
    watch_id = watch(make_review())
    before = len(delta_reviews(watch_id))

    outcome = asyncio.run(watch_service.tick())

    assert outcome.checked == 1
    assert outcome.unchanged == 1
    assert outcome.started == []
    assert github.compares == []
    assert len(delta_reviews(watch_id)) == before
    assert reload_watch(watch_id).last_checked_at is not None


def test_a_moved_head_creates_one_linked_delta_review(client, monkeypatch):
    github = configure(monkeypatch, GitHub(head=HEAD_B))
    provision(client)
    parent_id = make_review()
    watch_id = watch(parent_id)

    outcome = asyncio.run(watch_service.tick())

    assert outcome.started, outcome
    assert github.compares == [(HEAD_A, HEAD_B)]

    (review,) = delta_reviews(watch_id)
    assert review.id == outcome.started[0]
    assert review.watch_id == watch_id
    assert review.parent_review_id == parent_id
    assert review.trigger == ReviewTrigger.WATCH
    assert review.commit_id == HEAD_B
    assert review.status == ReviewStatus.DRAFT
    # Only the delta was reviewed: one thread, on the file the comparison produced.
    assert [thread.file_path for thread in review.threads] == ["src/services/billing.py"]
    assert review.threads[0].line_number == 2
    assert any(
        "Delta review" in note and f"#{parent_id}" in note for note in (review.notes or "").split("\n")
    )
    assert review.suggested_verdict == "COMMENT"

    updated = reload_watch(watch_id)
    assert updated.last_seen_commit_id == HEAD_B
    assert updated.last_review_id == review.id
    assert updated.last_error is None


def test_the_next_tick_is_a_no_op_after_a_delta_review(client, monkeypatch):
    github = configure(monkeypatch, GitHub(head=HEAD_B))
    provision(client)
    watch_id = watch(make_review())
    asyncio.run(watch_service.tick())

    outcome = asyncio.run(watch_service.tick())

    assert outcome.started == []
    assert outcome.unchanged == 1
    assert len(delta_reviews(watch_id)) == 1
    assert github.compares == [(HEAD_A, HEAD_B)]  # compared once, not again


def test_a_tick_that_lost_the_claim_does_nothing(client, monkeypatch):
    github = configure(monkeypatch, GitHub(head=HEAD_B))
    provision(client)
    watch_id = watch(make_review())

    def claim_first() -> None:
        """Another tick finishes this delta while we are still fetching the head."""
        with SessionLocal() as db:
            db.execute(
                text("UPDATE review_watches SET last_seen_commit_id = :head WHERE id = :id"),
                {"head": HEAD_B, "id": watch_id},
            )
            db.commit()

    github.before_fetch = claim_first
    outcome = asyncio.run(watch_service.tick())

    assert outcome.started == []
    assert outcome.skipped == 1
    assert delta_reviews(watch_id) == []


def test_a_stale_second_review_for_the_same_commit_is_rejected(client, monkeypatch):
    """Even past the claim, `UNIQUE(watch_id, commit_id)` refuses a second review of one commit."""
    configure(monkeypatch, GitHub(head=HEAD_B))
    provision(client)
    watch_id = watch(make_review())
    asyncio.run(watch_service.tick())

    # A second process that never saw the first one's claim replays the same delta.
    with SessionLocal() as db:
        db.execute(
            text("UPDATE review_watches SET last_seen_commit_id = :head WHERE id = :id"),
            {"head": HEAD_A, "id": watch_id},
        )
        db.commit()

    outcome = asyncio.run(watch_service.tick())

    assert outcome.started == []
    assert outcome.skipped == 1
    assert len(delta_reviews(watch_id)) == 1
    # The watch moved past the commit instead of retrying it forever.
    assert reload_watch(watch_id).last_seen_commit_id == HEAD_B
    assert asyncio.run(watch_service.tick()).unchanged == 1


def test_a_duplicate_watch_commit_pair_is_refused_by_the_database(client, monkeypatch):
    configure(monkeypatch, GitHub())
    provision(client)
    watch_id = watch(make_review())

    with SessionLocal() as db:
        for _ in range(2):
            db.add(
                CodeReview(
                    user_id=owner_id(),
                    pr_url=PR_URL,
                    vcs="github",
                    status=ReviewStatus.DRAFT,
                    commit_id=HEAD_B,
                    watch_id=watch_id,
                    trigger=ReviewTrigger.WATCH,
                )
            )
        with pytest.raises(IntegrityError):
            db.commit()


def test_a_failed_compare_keeps_the_delta_for_the_next_tick(client, monkeypatch):
    github = configure(monkeypatch, GitHub(head=HEAD_B, fail_compare=True))
    provision(client)
    watch_id = watch(make_review())

    outcome = asyncio.run(watch_service.tick())

    assert outcome.started == []
    assert outcome.failed and outcome.failed[0]["watch_id"] == watch_id
    assert "force-pushed" in outcome.failed[0]["error"]
    broken = reload_watch(watch_id)
    assert broken.last_seen_commit_id == HEAD_A  # the claim rolled back with the failure
    assert broken.last_error and "force-pushed" in broken.last_error
    assert delta_reviews(watch_id) == []

    # The next tick retries the same delta and succeeds.
    github.fail_compare = False
    outcome = asyncio.run(watch_service.tick())
    assert outcome.started, outcome
    assert reload_watch(watch_id).last_error is None


def test_a_disabled_watch_is_not_checked(client, monkeypatch):
    github = configure(monkeypatch, GitHub(head=HEAD_B))
    provision(client)
    watch_id = watch(make_review())
    with SessionLocal() as db:
        db.execute(
            text("UPDATE review_watches SET enabled = :off WHERE id = :id"),
            {"off": False, "id": watch_id},
        )
        db.commit()

    outcome = asyncio.run(watch_service.tick())

    assert outcome.checked == 0
    assert github.fetches == 0


def test_a_watch_without_a_base_adopts_the_head_instead_of_reviewing_everything(client, monkeypatch):
    github = configure(monkeypatch, GitHub(head=HEAD_B))
    provision(client)
    watch_id = watch(make_review(commit=None))

    outcome = asyncio.run(watch_service.tick())

    assert outcome.adopted == 1
    assert outcome.started == []
    assert github.compares == []
    assert reload_watch(watch_id).last_seen_commit_id == HEAD_B


def test_applying_a_delta_review_posts_only_its_own_rounds(client, monkeypatch):
    configure(monkeypatch, GitHub(head=HEAD_B))
    provision(client)
    parent_id = make_review()
    watch_id = watch(parent_id)
    asyncio.run(watch_service.tick())
    (review,) = delta_reviews(watch_id)

    # Accept the delta review's own finding.
    body = client.get(f"/api/reviews/{review.id}").json()
    (thread,) = body["threads"]
    decided = client.post(
        f"/api/reviews/{review.id}/rounds/{thread['rounds'][0]['id']}/decision",
        json={"decision": "accept", "summary": "**High** — confirmed."},
    )
    assert decided.status_code == 200, decided.text

    posted: list[dict] = []

    async def fake_post(token, repo_full_name, number, payload, base_url=None):
        posted.append(payload)
        return {"html_url": "https://github.com/octo/example/pull/123#pullrequestreview-9", "id": 9}

    async def no_reply(*args, **kwargs):
        return {}

    async def live_diff(token, owner, repo, number, base_url=None):
        # Apply re-validates anchors against the pull request's live diff, as it always has; the
        # delta's lines are a subset of it, so the comparison result is a faithful stand-in.
        return DELTA_DIFF

    monkeypatch.setattr(github_service, "post_review", fake_post)
    monkeypatch.setattr(github_service, "post_reply", no_reply)
    monkeypatch.setattr(github_service, "fetch_diff", live_diff)

    response = client.post(f"/api/reviews/{review.id}/apply", json={"event": "REQUEST_CHANGES"})
    assert response.status_code == 200, response.text
    assert len(posted) == 1
    assert [comment["path"] for comment in posted[0]["comments"]] == ["src/services/billing.py"]

    # The parent review is untouched: still a draft with nothing applied.
    parent = client.get(f"/api/reviews/{parent_id}").json()
    assert parent["status"] == "draft"
    assert parent["github_review_url"] is None
