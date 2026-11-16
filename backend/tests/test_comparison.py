"""Side-by-side comparison: the sibling review, the merge buckets, pricing and the apply guard."""

from __future__ import annotations

import json

from sqlalchemy import select, text

from app.db.session import SessionLocal
from app.models.llm_call import LLMCall
from app.models.review import (
    CodeReview,
    MessageRole,
    ReviewStatus,
    ReviewThread,
    RoundStatus,
    ThreadMessage,
    ThreadRound,
)
from app.models.watch import ReviewTrigger
from app.services import llm_service
from app.services.finding_search import normalise
from tests.conftest import TEST_EMAIL, wait_for_review
from tests.fixtures import PR_URL, llm_result, provision

FINDINGS = [
    {
        "filePath": "src/services/auth.py",
        "lineNumber": 11,
        "diffHunk": "",
        "initialComment": "**High** — unbounded query; paginate it.",
    },
    {
        "filePath": "src/services/auth.py",
        "lineNumber": 12,
        "diffHunk": "",
        "initialComment": "**Medium** — logging leaks row counts.",
    },
]


def _user_id() -> int:
    with SessionLocal() as db:
        return db.execute(
            text("SELECT id FROM users WHERE email = :email"), {"email": TEST_EMAIL}
        ).scalar_one()


def _review(*, trigger: str | None = None, parent: int | None = None, model: str = "ollama-local:llama3") -> int:
    with SessionLocal() as db:
        review = CodeReview(
            user_id=_user_id(),
            pr_url=PR_URL,
            vcs="github",
            pr_title="Harden query limits",
            pr_number=123,
            repo_full_name="octo/example",
            commit_id="abc123sha",
            model_used=model,
            skill_foundation="code-review",
            status=ReviewStatus.DRAFT,
            trigger=trigger,
            parent_review_id=parent,
        )
        db.add(review)
        db.commit()
        db.refresh(review)
        return review.id


def _thread(review_id: int, text: str, line: int) -> int:
    with SessionLocal() as db:
        thread = ReviewThread(
            review_id=review_id,
            file_path="src/services/auth.py",
            line_number=line,
            diff_hunk="@@ -10,4 +10,5 @@\n+code",
            origin="AI_GENERATED",
            norm_key=normalise(text),
        )
        thread.messages.append(
            ThreadMessage(role=MessageRole.ASSISTANT, content=text, round_number=1)
        )
        thread.rounds.append(ThreadRound(round_number=1, status=RoundStatus.DRAFTING))
        db.add(thread)
        db.commit()
        db.refresh(thread)
        return thread.id


def test_merge_buckets_a_shared_finding_and_two_unique_ones(client):
    primary = _review()
    sibling = _review(trigger=ReviewTrigger.COMPARISON, parent=primary)
    _thread(primary, "**High** — unbounded query", line=11)
    _thread(sibling, "high: unbounded query", line=13)  # ±2 lines, same key -> both
    _thread(primary, "**Low** — rename this helper", line=40)
    _thread(sibling, "**Medium** — add a retry here", line=41)  # different key -> split

    body = client.get(f"/api/reviews/{sibling}/comparison").json()

    assert body["primary"]["id"] == primary
    assert body["comparison"]["id"] == sibling
    assert len(body["both"]) == 1
    assert body["both"][0]["primary_line"] == 11
    assert body["both"][0]["comparison_line"] == 13
    assert [item["line_number"] for item in body["primary_only"]] == [40]
    assert [item["line_number"] for item in body["comparison_only"]] == [41]
    assert body["line_tolerance"] == 2

    # The same view is available from the primary side.
    from_primary = client.get(f"/api/reviews/{primary}/comparison").json()
    assert from_primary == body


def test_same_line_without_a_shared_key_still_merges(client):
    primary = _review()
    sibling = _review(trigger=ReviewTrigger.COMPARISON, parent=primary)
    _thread(primary, "unbounded query", line=11)
    _thread(sibling, "a completely different defect", line=11)

    body = client.get(f"/api/reviews/{primary}/comparison").json()
    assert len(body["both"]) == 1
    assert body["primary_only"] == []
    assert body["comparison_only"] == []


def test_no_comparison_is_a_404(client):
    review = _review()
    assert client.get(f"/api/reviews/{review}/comparison").status_code == 404


def test_estimate_uses_the_primary_usage_and_the_price_table(client):
    primary = _review()
    with SessionLocal() as db:
        db.add(
            LLMCall(
                review_id=primary,
                purpose="ingest",
                provider="ollama-cloud",
                model="deepseek-v4-pro",
                prompt_tokens=1000,
                completion_tokens=500,
                total_tokens=1500,
                latency_ms=100,
                ok=True,
            )
        )
        db.commit()

    body = client.get(
        f"/api/reviews/{primary}/comparison/estimate",
        params={"model": "ollama-cloud:deepseek-v4-pro"},
    ).json()
    assert body["prompt_tokens"] == 1000
    assert body["completion_tokens"] == 500
    # 1000/1e6 * 1.32 + 500/1e6 * 3.96 = 0.0033
    assert abs(body["estimated_cost_usd"] - 0.0033) < 1e-9
    assert "Estimate" in body["note"] or "Estimated" in body["note"]

    missing = client.get(
        f"/api/reviews/{primary}/comparison/estimate", params={"model": "not-a-model"}
    )
    assert missing.status_code == 422


def test_compare_creates_a_linked_sibling_and_apply_refuses_it(client, monkeypatch):
    from app.api.routes import reviews as reviews_routes

    provision(client)
    primary = _review()
    monkeypatch.setattr(reviews_routes, "schedule_ingest", lambda *args, **kwargs: None)

    response = client.post(
        f"/api/reviews/{primary}/compare", json={"model": "ollama-local:llama3"}
    )
    assert response.status_code == 202, response.text
    sibling_id = response.json()["id"]

    with SessionLocal() as db:
        sibling = db.get(CodeReview, sibling_id)
        assert sibling.parent_review_id == primary
        assert sibling.trigger == ReviewTrigger.COMPARISON
        assert sibling.commit_id == "abc123sha"

    refused = client.post(f"/api/reviews/{sibling_id}/apply", json={"event": "COMMENT"})
    assert refused.status_code == 409
    assert "read-only" in refused.json()["detail"]


def test_comparison_and_primary_both_write_ledger_rows(client, monkeypatch):
    async def adapter(provider, base_url, headers, name, system_prompt, user_prompt, config, json_mode=False):
        return llm_result(json.dumps({"verdict": "COMMENT", "confidence": 70, "findings": FINDINGS}))

    from app.services import github_service

    async def fetch_pr(token, owner, repo, number, base_url=None):
        from tests.test_review_pipeline import fake_fetch_pr

        return fake_fetch_pr(token, owner, repo, number, base_url)

    async def fetch_diff(token, owner, repo, number, base_url=None):
        from tests.fixtures import SAMPLE_DIFF

        return SAMPLE_DIFF

    async def no_comments(token, repo_full_name, number, base_url=None):
        return []

    # Patch the provider adapter, one level below `generate`: the wrapper, the ledger insert and
    # the per-call usage line all run, with no network.
    monkeypatch.setattr(llm_service, "_generate_ollama", adapter)
    monkeypatch.setattr(github_service, "fetch_pr", fetch_pr)
    monkeypatch.setattr(github_service, "fetch_diff", fetch_diff)
    monkeypatch.setattr(github_service, "fetch_review_comments", no_comments)
    provision(client)

    primary = client.post("/api/reviews", json={"pr_url": PR_URL, "model": "ollama-local:llama3"})
    assert primary.status_code == 202, primary.text
    primary_body = wait_for_review(client, primary.json()["id"], timeout=15)
    assert primary_body["status"] == "draft"

    sibling = client.post(
        f"/api/reviews/{primary_body['id']}/compare", json={"model": "ollama-local:llama3"}
    )
    assert sibling.status_code == 202, sibling.text
    sibling_id = sibling.json()["id"]
    wait_for_review(client, sibling_id, timeout=15)

    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(LLMCall).where(
                    LLMCall.review_id.in_((primary_body["id"], sibling_id))
                )
            )
        )
    assert {row.review_id for row in rows} == {primary_body["id"], sibling_id}
    assert all(row.purpose == "ingest" for row in rows)
    assert {row.model for row in rows} == {"llama3"}
