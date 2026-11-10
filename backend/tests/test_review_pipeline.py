from __future__ import annotations

import json

from app.services import github_service, llm_service
from app.services.pull_request import PullRequestInfo
from tests.fixtures import PR_URL, SAMPLE_DIFF, llm_result, provision

FINDINGS = [
    {
        "filePath": "src/services/auth.py",
        "lineNumber": 11,
        "diffHunk": '+    rows = db.query(Model).limit(limit).all()',
        "initialComment": "**High** — unbounded query replaced by a limit; verify `limit` is validated.",
    },
    {
        "filePath": "src/services/auth.py",
        "lineNumber": 12,
        "diffHunk": "",
        "initialComment": "Logging every fetch at debug is fine, but the message leaks row counts.",
    },
]


def fake_fetch_pr(token, owner, repo, number, base_url=None):
    return PullRequestInfo(
        vcs="github",
        project=f"{owner}/{repo}",
        number=number,
        title="Harden query limits",
        state="open",
        draft=False,
        head_sha="abc123sha",
        base_sha="base123sha",
        start_sha="base123sha",
        base_ref="main",
        html_url=PR_URL,
        author="octocat",
        body="Adds a limit to the query.",
        additions=2,
        deletions=1,
        changed_files=1,
    )


async def fake_fetch_pr_async(token, owner, repo, number, base_url=None):
    return fake_fetch_pr(token, owner, repo, number, base_url)


async def fake_fetch_diff(token, owner, repo, number, base_url=None):
    return SAMPLE_DIFF


async def fake_fetch_comments(token, repo_full_name, number, base_url=None):
    return []


def configure(monkeypatch, llm_payload: str, comments=None):
    monkeypatch.setattr(github_service, "fetch_pr", fake_fetch_pr_async)
    monkeypatch.setattr(github_service, "fetch_diff", fake_fetch_diff)

    async def fetch_comments(token, repo_full_name, number, base_url=None):
        return list(comments or [])

    monkeypatch.setattr(github_service, "fetch_review_comments", fetch_comments)
    monkeypatch.setattr(llm_service, "generate", lambda *args, **kwargs: _result(llm_payload))


async def _result(payload: str):
    return llm_result(payload)


def test_ingest_creates_anchored_threads(client, monkeypatch):
    from tests.conftest import start_review

    configure(monkeypatch, json.dumps(FINDINGS))
    provision(client)

    body = start_review(client, PR_URL, "ollama-local:llama3")

    assert body["pr_title"] == "Harden query limits"
    assert body["commit_id"] == "abc123sha"
    assert body["model_used"] == "ollama-local:llama3"
    assert body["status"] == "draft"
    assert body["thread_count"] == 2
    assert body["skill_foundation"] == "code-review"

    thread = body["threads"][0]
    assert thread["file_path"] == "src/services/auth.py"
    assert thread["line_number"] == 11
    assert thread["side"] == "RIGHT"
    assert "limit(limit)" in thread["diff_hunk"]
    assert thread["messages"][0]["role"] == "assistant"
    assert thread["messages"][0]["content"].startswith("**High**")

    # The second finding had an empty diffHunk, so the backend rebuilt the quote.
    assert "@@" in body["threads"][1]["diff_hunk"]


def test_out_of_diff_findings_are_dropped_with_a_warning(client, monkeypatch):
    payload = json.dumps(
        [
            {
                "filePath": "src/unknown.py",
                "lineNumber": 5,
                "diffHunk": "",
                "initialComment": "Should be dropped",
            },
            {
                "filePath": "src/services/auth.py",
                "lineNumber": 99,
                "diffHunk": "",
                "initialComment": "Snapped to the last hunk line",
            },
        ]
    )
    configure(monkeypatch, payload)
    provision(client)

    from tests.conftest import start_review

    body = start_review(client, PR_URL, "ollama-local:llama3")
    assert body["thread_count"] == 1
    assert body["threads"][0]["line_number"] == 13
    assert any("not in the diff" in warning for warning in body["warnings"])


def test_llm_prose_response_fails_the_review(client, monkeypatch):
    configure(monkeypatch, "I reviewed the code and it looks fine to me.")
    provision(client)

    from tests.conftest import start_review

    body = start_review(client, PR_URL, "ollama-local:llama3")
    assert body["status"] == "failed"
    assert "no parsable JSON" in body["error"]
    assert body["threads"] == []


def test_invalid_url_is_400(client, monkeypatch):
    configure(monkeypatch, "[]")
    provision(client)

    response = client.post(
        "/api/reviews", json={"pr_url": "https://example.com/not-a-pr", "model": "ollama-local:llama3"}
    )
    assert response.status_code == 400
    assert "GitHub pull request URL" in response.json()["detail"]


def test_missing_token_is_400_naming_settings(client):
    for key in client.get("/api/keys/version-control").json():
        client.delete(f"/api/keys/version-control/{key['id']}")
    response = client.post("/api/reviews", json={"pr_url": PR_URL, "model": "ollama-local:llama3"})
    assert response.status_code == 400
    assert "Settings" in response.json()["detail"]


def test_unknown_model_is_422(client, monkeypatch):
    configure(monkeypatch, "[]")
    provision(client)
    response = client.post("/api/reviews", json={"pr_url": PR_URL, "model": "gpt-4"})
    assert response.status_code == 422
    assert "Unknown model id" in response.json()["detail"]


def test_failed_llm_call_records_the_error_on_the_review(client, monkeypatch):
    from tests.conftest import start_review

    async def boom(*args, **kwargs):
        raise llm_service.LLMError("Ollama does not have the model 'nope'. Pull it first.")

    configure(monkeypatch, "[]")
    monkeypatch.setattr(llm_service, "generate", boom)
    provision(client)

    body = start_review(client, PR_URL, "ollama-local:nope")
    assert body["status"] == "failed"
    assert body["error"].startswith("Ollama does not have the model")
    assert body["threads"] == []


def test_reviews_list_reflects_created_rows(client, monkeypatch):
    from tests.conftest import start_review

    configure(monkeypatch, "[]")
    provision(client)
    start_review(client, PR_URL, "ollama-local:llama3")

    listing = client.get("/api/reviews").json()
    assert len(listing) == 1
    assert listing[0]["repo_full_name"] == "octo/example"
    assert listing[0]["thread_count"] == 0


def test_verdict_and_confidence_are_stored(client, monkeypatch):
    from tests.conftest import start_review

    payload = {
        "verdict": "request_changes",
        "confidence": "88%",
        "findings": FINDINGS,
    }
    configure(monkeypatch, json.dumps(payload))
    provision(client)

    body = start_review(client, PR_URL, "ollama-local:llama3")
    assert body["suggested_verdict"] == "REQUEST_CHANGES"
    assert body["confidence_percentage"] == 88
    assert body["thread_count"] == 2


def test_legacy_array_response_leaves_the_opinion_empty(client, monkeypatch):
    from tests.conftest import start_review

    configure(monkeypatch, json.dumps(FINDINGS))
    provision(client)

    body = start_review(client, PR_URL, "ollama-local:llama3")
    assert body["suggested_verdict"] is None
    assert body["confidence_percentage"] is None


def test_invalid_verdict_is_dropped_but_findings_are_kept(client, monkeypatch):
    from tests.conftest import start_review

    payload = {"verdict": "MERGE_IT", "confidence": 140, "findings": FINDINGS}
    configure(monkeypatch, json.dumps(payload))
    provision(client)

    body = start_review(client, PR_URL, "ollama-local:llama3")
    assert body["suggested_verdict"] is None
    assert body["confidence_percentage"] == 100  # clamped
    assert body["thread_count"] == 2


def test_models_endpoint_lists_skills_and_degrades_without_ollama(client, monkeypatch):
    async def unreachable(base_url, api_key=None, timeout=10.0, label="Ollama"):
        return False, f"{label} is unreachable", None

    monkeypatch.setattr(llm_service, "probe_ollama", unreachable)
    provision(client, llm="ollama_local", default_model="llama3:8b")

    response = client.get("/api/models")
    assert response.status_code == 200
    body = response.json()
    assert any(name.endswith("SKILL.md") for name in body["skills"])
    assert isinstance(body["models"], list)
    local = next(m for m in body["models"] if m["provider"] == "ollama-local")
    assert local["available"] is False
    assert "unreachable" in local["note"]


def test_unexpected_ingest_error_fails_the_review(client, monkeypatch):
    """A crash the pipeline does not expect must not leave the review `running` forever."""
    import asyncio

    from sqlalchemy import text

    from app.db.session import SessionLocal
    from app.models.review import CodeReview, ReviewStatus
    from app.services import review_pipeline
    from app.services.progress import bus
    from tests.conftest import TEST_EMAIL

    with SessionLocal() as db:
        user_id = db.execute(
            text("SELECT id FROM users WHERE email = :email"), {"email": TEST_EMAIL}
        ).scalar_one()
        review = CodeReview(
            user_id=user_id,
            pr_url=PR_URL,
            vcs="github",
            model_used="ollama-cloud:deepseek",
            skill_foundation="code-review",
            status=ReviewStatus.RUNNING,
        )
        db.add(review)
        db.commit()
        review_id = review.id

    async def explode(db_session, review_row):
        raise RuntimeError('column "author" of relation "thread_messages" does not exist')

    monkeypatch.setattr(review_pipeline, "execute", explode)
    asyncio.run(review_pipeline.run_ingest(review_id))

    with SessionLocal() as db:
        row = db.get(CodeReview, review_id)
        assert row.status == ReviewStatus.FAILED
        assert row.error is not None
        assert 'column "author"' in row.error
        assert "Traceback" not in row.error

    events = bus.history(review_id)
    assert events and events[-1].level == "error"
    assert events[-1].terminal is True
    assert "column \"author\"" in (events[-1].detail or "")

