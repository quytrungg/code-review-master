"""Cross-review finding search, "seen before" and the recurring-issue digest."""

from __future__ import annotations

import json

from sqlalchemy import text

from app.db.session import SessionLocal
from app.models.review import (
    CodeReview,
    MessageRole,
    ReviewStatus,
    ReviewThread,
    RoundStatus,
    ThreadMessage,
    ThreadOrigin,
    ThreadRound,
)
from app.services import llm_service
from app.services.finding_search import normalise
from tests.conftest import TEST_EMAIL, start_review
from tests.fixtures import PR_URL, llm_result, provision


def _user_id(email: str = TEST_EMAIL) -> int:
    with SessionLocal() as db:
        return db.execute(
            text("SELECT id FROM users WHERE email = :email"), {"email": email}
        ).scalar_one()


def _review(*, repo: str = "octo/example", status: str = ReviewStatus.DRAFT) -> int:
    with SessionLocal() as db:
        review = CodeReview(
            user_id=_user_id(),
            pr_url=PR_URL,
            vcs="github",
            repo_full_name=repo,
            pr_number=1,
            model_used="ollama-local:llama3",
            skill_foundation="code-review",
            status=status,
        )
        db.add(review)
        db.commit()
        db.refresh(review)
        return review.id


def _thread(
    review_id: int,
    content: str,
    *,
    path: str = "src/auth.py",
    line: int = 11,
    accepted: bool = False,
    origin: str = ThreadOrigin.AI_GENERATED,
) -> int:
    with SessionLocal() as db:
        thread = ReviewThread(
            review_id=review_id,
            file_path=path,
            line_number=line,
            diff_hunk="@@ -1 +1 @@\n+code",
            origin=origin,
            norm_key=normalise(content),
        )
        thread.messages.append(
            ThreadMessage(role=MessageRole.ASSISTANT, content=content, round_number=1)
        )
        thread.rounds.append(
            ThreadRound(
                round_number=1,
                status=RoundStatus.PUBLISHED if accepted else RoundStatus.DRAFTING,
                final_summary=content if accepted else None,
            )
        )
        db.add(thread)
        db.commit()
        db.refresh(thread)
        return thread.id


def test_normalise_strips_severity_and_markdown():
    assert normalise("**High** — the query is unbounded") == "the query is unbounded"
    assert normalise("Critical: committed token `ghp_x` in config") == "committed token in config"
    assert normalise("HIGH — Unbounded QUERY!") == "unbounded query"
    assert normalise("") == ""


def test_search_finds_the_same_finding_in_two_reviews(client):
    first = _review()
    second = _review()
    _thread(first, "**High** — unbounded query; paginate it.")
    _thread(second, "high: unbounded query needs a limit.")

    response = client.get("/api/findings/search", params={"q": "unbounded query"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert {item["review_id"] for item in body["items"]} == {first, second}
    assert all(item["snippet"] for item in body["items"])


def test_repo_filter_separates_repositories(client):
    here = _review(repo="octo/example")
    elsewhere = _review(repo="other/lib")
    _thread(here, "unbounded query; paginate it.")
    _thread(elsewhere, "unbounded query; paginate it.")

    scoped = client.get(
        "/api/findings/search", params={"q": "unbounded query", "repo": "octo/example"}
    ).json()
    assert [item["review_id"] for item in scoped["items"]] == [here]

    broad = client.get("/api/findings/search", params={"q": "unbounded query"}).json()
    assert {item["review_id"] for item in broad["items"]} == {here, elsewhere}


def test_path_and_empty_request(client):
    review = _review()
    _thread(review, "unbounded query; paginate it.", path="src/services/auth.py")

    by_path = client.get("/api/findings/search", params={"path": "services/auth"}).json()
    assert by_path["total"] == 1
    assert by_path["items"][0]["file_path"] == "src/services/auth.py"

    assert client.get("/api/findings/search").status_code == 422


def test_similar_returns_prior_threads_with_acceptance(client):
    repo = "octo/example"
    older = _review(repo=repo)
    newer = _review(repo=repo)
    other_repo = _review(repo="other/lib")

    old_thread = _thread(older, "**High** — unbounded query", accepted=True)
    new_thread = _thread(newer, "high: unbounded query")
    _thread(other_repo, "high: unbounded query", line=12)

    response = client.get(f"/api/findings/similar/{newer}/{new_thread}")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["thread_id"] for item in items] == [old_thread]
    assert items[0]["accepted"] is True
    assert items[0]["repo_full_name"] == repo


def test_similar_is_a_404_for_another_account(client, second_client):
    review = _review()
    thread = _thread(review, "unbounded query")

    assert client.get(f"/api/findings/similar/{review}/{thread}").status_code == 200
    assert second_client.get(f"/api/findings/similar/{review}/{thread}").status_code == 404
    assert second_client.get(f"/api/findings/similar/{review}/999999").status_code == 404


def test_recurring_groups_by_repo_and_key(client):
    repo = "octo/example"
    first = _review(repo=repo)
    second = _review(repo=repo)
    _thread(first, "**High** — unbounded query")
    _thread(second, "high: unbounded query")
    _thread(second, "a completely different finding")

    body = client.get("/api/analytics?days=90").json()
    recurring = body["recurring"]
    assert len(recurring) == 1
    assert recurring[0]["repo_full_name"] == repo
    assert recurring[0]["key"] == "unbounded query"
    assert recurring[0]["reviews"] == 2
    assert recurring[0]["findings"] == 2
    assert recurring[0]["last_seen"]


def test_pipeline_indexes_a_new_finding(client, monkeypatch):
    from tests.test_review_pipeline import configure

    payload = json.dumps(
        {
            "verdict": "COMMENT",
            "confidence": 70,
            "findings": [
                {
                    "filePath": "src/services/auth.py",
                    "lineNumber": 11,
                    "diffHunk": "",
                    "initialComment": "**High** — the query is unbounded; paginate it.",
                }
            ],
        }
    )
    configure(monkeypatch, payload)
    provision(client)

    body = start_review(client, PR_URL, "ollama-local:llama3")
    assert body["thread_count"] == 1

    hits = client.get("/api/findings/search", params={"q": "query is unbounded"}).json()
    assert hits["total"] == 1
    assert hits["items"][0]["review_id"] == body["id"]
    assert hits["items"][0]["origin"] in ("AI_GENERATED", "CHECK")
