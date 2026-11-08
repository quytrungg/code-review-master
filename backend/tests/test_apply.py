from __future__ import annotations

import json

import pytest

from app.services import github_service, llm_service
from app.services.github_service import GitHubError
from tests.fixtures import accept_findings, provision
from tests.test_review_pipeline import FINDINGS, configure

PR_URL = "https://github.com/octo/example/pull/123"


def seed_review(client, monkeypatch, findings=None) -> dict:
    from tests.conftest import start_review

    configure(monkeypatch, json.dumps(findings or FINDINGS))
    provision(client)
    return start_review(client, PR_URL, "ollama-local:llama3")


def stub_post(monkeypatch, responses):
    """responses: list of dict payloads or exceptions, consumed in order."""
    calls: list[dict] = []

    async def fake_post(token, repo_full_name, number, payload, base_url=None):
        calls.append({"token": token, "repo": repo_full_name, "number": number, "payload": payload})
        outcome = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(github_service, "post_review", fake_post)
    return calls


def test_apply_posts_the_review_payload_and_marks_applied(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    first, second = review["threads"][0]["id"], review["threads"][1]["id"]
    accepted = {
        first: "**High** — bounded query, verified.",
        second: "**Medium** — logging fixed in 9f1c.",
    }
    for thread in review["threads"]:
        round_id = thread["rounds"][0]["id"]
        response = client.post(
            f"/api/reviews/{review['id']}/rounds/{round_id}/decision",
            json={"decision": "accept", "summary": accepted[thread["id"]]},
        )
        assert response.status_code == 200, response.text

    calls = stub_post(monkeypatch, [{"html_url": "https://github.com/octo/example/pull/123#pullrequestreview-1"}])

    response = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "REQUEST_CHANGES"})
    assert response.status_code == 200, response.text
    body = response.json()

    assert len(calls) == 1
    payload = calls[0]["payload"]
    assert payload["commit_id"] == "abc123sha"
    assert payload["event"] == "REQUEST_CHANGES"
    assert "body" not in payload  # inline comments only
    assert len(payload["comments"]) == 2
    first_comment = payload["comments"][0]
    assert first_comment["path"] == "src/services/auth.py"
    assert first_comment["line"] == 11
    assert first_comment["side"] == "RIGHT"
    assert first_comment["body"] == "**High** — bounded query, verified."

    assert body["comments_posted"] == 2
    assert body["dropped"] == []
    assert body["github_review_url"].endswith("#pullrequestreview-1")
    assert body["review"]["status"] == "applied"
    assert body["review"]["verdict"] == "REQUEST_CHANGES"

    stored = client.get(f"/api/reviews/{review['id']}").json()
    assert stored["status"] == "applied"
    assert stored["threads"][0]["rounds"][0]["final_summary"] == "**High** — bounded query, verified."
    assert stored["threads"][0]["ordinal"] == 1


def test_apply_refuses_a_review_where_nothing_is_accepted(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    calls = stub_post(monkeypatch, [{"html_url": "https://github.com/octo/example/pull/123#pullrequestreview-0"}])

    response = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"})
    assert response.status_code == 400
    assert "Nothing is accepted" in response.json()["detail"]
    assert calls == []
    assert client.get(f"/api/reviews/{review['id']}").json()["status"] == "draft"


def test_apply_only_exports_selected_threads(client, monkeypatch):
    review = accept_findings(client, seed_review(client, monkeypatch))
    calls = stub_post(monkeypatch, [{"html_url": "https://github.com/octo/example/pull/123#pullrequestreview-2"}])
    chosen = review["threads"][1]["id"]

    response = client.post(
        f"/api/reviews/{review['id']}/apply",
        json={"event": "COMMENT", "thread_ids": [chosen]},
    )
    assert response.status_code == 200
    assert len(calls[0]["payload"]["comments"]) == 1
    assert calls[0]["payload"]["comments"][0]["line"] == 12


def test_accepted_text_is_exported_not_the_transcript(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    thread_id = review["threads"][0]["id"]
    round_id = review["threads"][0]["rounds"][0]["id"]

    async def reply(settings_row, model, system_prompt, user_prompt, json_mode=False):
        return "An allowlist is the right fix."

    monkeypatch.setattr(llm_service, "generate", reply)
    client.post(
        f"/api/reviews/{review['id']}/discuss",
        json={"threads": [{"thread_id": thread_id, "message": "Could we allowlist instead?"}]},
    )

    client.post(
        f"/api/reviews/{review['id']}/rounds/{round_id}/decision",
        json={
            "decision": "accept",
            "summary": "**High** — replaced with an allowlist after discussion (8a1c).",
        },
    )
    calls = stub_post(monkeypatch, [{"html_url": "https://github.com/octo/example/pull/123#pullrequestreview-3"}])
    response = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"})
    assert response.status_code == 200

    exported = {comment["line"]: comment["body"] for comment in calls[0]["payload"]["comments"]}
    assert exported[11] == "**High** — replaced with an allowlist after discussion (8a1c)."
    assert "AI Review Conclusion" not in exported[11]


def test_pushed_back_finding_is_not_in_the_payload(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    keep = review["threads"][0]
    withdrawn = review["threads"][1]

    client.post(
        f"/api/reviews/{review['id']}/rounds/{keep['rounds'][0]['id']}/decision",
        json={"decision": "accept", "summary": "**High** — still valid."},
    )
    pushed = client.post(
        f"/api/reviews/{review['id']}/rounds/{withdrawn['rounds'][0]['id']}/decision",
        json={"decision": "push_back"},
    )
    assert pushed.status_code == 200, pushed.text

    calls = stub_post(monkeypatch, [{"html_url": "https://github.com/octo/example/pull/123#pullrequestreview-9"}])
    response = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"})
    assert response.status_code == 200
    body = response.json()

    payload = calls[0]["payload"]
    assert "body" not in payload
    assert len(payload["comments"]) == 1
    assert payload["comments"][0]["line"] == 11
    assert body["comments_posted"] == 1

    stored = client.get(f"/api/reviews/{review['id']}").json()
    flags = {thread["id"]: thread["dropped"] for thread in stored["threads"]}
    assert flags[withdrawn["id"]] is True and flags[keep["id"]] is False


def test_apply_does_not_need_the_summariser(client, monkeypatch):
    review = accept_findings(client, seed_review(client, monkeypatch))

    async def unavailable(*args, **kwargs):
        raise llm_service.LLMError("summariser unavailable")

    monkeypatch.setattr(llm_service, "generate", unavailable)
    calls = stub_post(monkeypatch, [{"html_url": "https://github.com/octo/example/pull/123#pullrequestreview-10"}])

    response = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"})
    assert response.status_code == 200
    body = response.json()

    assert body["summarised"] is False
    assert body["comments_posted"] == 2
    assert calls[0]["payload"]["comments"][0]["body"].startswith("**High**")


def test_stale_anchors_leave_nothing_to_publish(client, monkeypatch):
    review = accept_findings(client, seed_review(client, monkeypatch))

    # The branch moved: only line 12 survived in the new diff.
    moved_diff = (
        "diff --git a/src/services/auth.py b/src/services/auth.py\n"
        "--- a/src/services/auth.py\n"
        "+++ b/src/services/auth.py\n"
        "@@ -90,3 +90,4 @@ def handler(request):\n"
        "     limit = 10\n"
        "+    log.debug('moved')\n"
        "     return rows\n"
    )

    async def moved(token, owner, repo, number, base_url=None):
        return moved_diff

    monkeypatch.setattr(github_service, "fetch_diff", moved)
    calls = stub_post(monkeypatch, [{"html_url": "https://github.com/octo/example/pull/123#pullrequestreview-4"}])

    response = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"})
    assert response.status_code == 422
    assert "Nothing to publish" in response.json()["detail"]
    assert calls == []
    assert client.get(f"/api/reviews/{review['id']}").json()["status"] == "draft"


def test_github_rejection_is_reported_without_a_retry(client, monkeypatch):
    review = accept_findings(client, seed_review(client, monkeypatch))
    calls = stub_post(
        monkeypatch,
        [GitHubError("GitHub rejected the review: invalid comment anchor", 422)],
    )

    response = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"})
    assert response.status_code == 502
    assert "invalid comment anchor" in response.json()["detail"]
    assert len(calls) == 1
    assert client.get(f"/api/reviews/{review['id']}").json()["status"] == "draft"


def test_apply_is_not_repeatable(client, monkeypatch):
    review = accept_findings(client, seed_review(client, monkeypatch))
    calls = stub_post(monkeypatch, [{"html_url": "https://github.com/octo/example/pull/123#pullrequestreview-6"}])

    assert client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"}).status_code == 200
    second = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"})
    assert second.status_code == 409
    assert len(calls) == 1


def test_apply_without_token_is_400(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    for key in client.get("/api/keys/version-control").json():
        client.delete(f"/api/keys/version-control/{key['id']}")
    stub_post(monkeypatch, [{"html_url": "x"}])

    response = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"})
    assert response.status_code == 400
    assert "Settings" in response.json()["detail"]


def test_apply_with_foreign_thread_id_is_400(client, monkeypatch):
    first = seed_review(client, monkeypatch)
    second = seed_review(client, monkeypatch)
    stub_post(monkeypatch, [{"html_url": "x"}])

    response = client.post(
        f"/api/reviews/{first['id']}/apply",
        json={"event": "COMMENT", "thread_ids": [second["threads"][0]["id"]]},
    )
    assert response.status_code == 400
    assert "does not belong" in response.json()["detail"]


@pytest.mark.parametrize("event", ["APPROVE", "REQUEST_CHANGES", "COMMENT"])
def test_all_verdicts_are_accepted(client, monkeypatch, event):
    review = accept_findings(client, seed_review(client, monkeypatch))
    calls = stub_post(monkeypatch, [{"html_url": "https://github.com/octo/example/pull/123#pullrequestreview-7"}])
    response = client.post(f"/api/reviews/{review['id']}/apply", json={"event": event})
    assert response.status_code == 200
    assert calls[0]["payload"]["event"] == event
    assert response.json()["review"]["verdict"] == event


def test_unknown_event_is_422(client, monkeypatch):
    review = seed_review(client, monkeypatch)
    response = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "MERGE"})
    assert response.status_code == 422


def test_github_failure_leaves_the_review_untouched(client, monkeypatch):
    review = accept_findings(client, seed_review(client, monkeypatch))
    stub_post(monkeypatch, [GitHubError("GitHub returned HTTP 500", 500)])

    response = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"})
    assert response.status_code == 502

    stored = client.get(f"/api/reviews/{review['id']}").json()
    assert stored["status"] == "draft"
    assert stored["github_review_url"] is None
    assert stored["verdict"] is None
