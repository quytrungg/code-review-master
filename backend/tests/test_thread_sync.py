"""Importing, syncing and delta-applying existing GitHub review threads."""

from __future__ import annotations

import json

from app.services import github_service, llm_service
from app.services.apply_service import pending_round_count
from app.services.thread_sync import group_comments
from tests.fixtures import MR_URL, accept_findings, as_result, provision
from tests.test_review_pipeline import FINDINGS, configure

PR_URL = "https://github.com/octo/example/pull/123"
PATH = "src/services/auth.py"


def comment(
    comment_id: int,
    body: str,
    *,
    author: str = "octocat",
    parent: int | None = None,
    path: str = PATH,
    line: int = 11,
    review_id: int | None = None,
):
    payload = {
        "id": comment_id,
        "body": body,
        "path": path,
        "line": line,
        "diff_hunk": "@@ -10,4 +10,5 @@ def handler(request):",
        "user": {"login": author},
        "created_at": "2026-11-07T10:00:00Z",
    }
    if parent is not None:
        payload["in_reply_to_id"] = parent
    if review_id is not None:
        payload["pull_request_review_id"] = review_id
    return payload


def stub_comments(monkeypatch, items):
    """Serve the given comment list live, so a test can append between syncs."""

    async def fetch_comments(token, repo_full_name, number, base_url=None):
        return list(items)

    monkeypatch.setattr(github_service, "fetch_review_comments", fetch_comments)
    return items


def set_review_url(review_id: int, url: str) -> None:
    """Record the published review URL, which is what identifies this review's own comments."""
    from app.db.session import SessionLocal
    from app.models.review import CodeReview

    db = SessionLocal()
    try:
        row = db.get(CodeReview, review_id)
        row.github_review_url = url
        db.commit()
    finally:
        db.close()


def stub_review_post(monkeypatch, review_id: int | None = 900):
    calls: list[dict] = []

    async def fake_post(token, repo_full_name, number, payload, base_url=None):
        calls.append(payload)
        body = {"html_url": f"{PR_URL}#pullrequestreview-{review_id}"}
        if review_id is not None:
            body["id"] = review_id
        return body

    monkeypatch.setattr(github_service, "post_review", fake_post)
    return calls


def stub_review_comments(monkeypatch, items):
    async def fake_list(token, repo_full_name, number, review_id, base_url=None):
        return list(items)

    monkeypatch.setattr(github_service, "fetch_review_id_comments", fake_list)
    return items


def stub_reply(monkeypatch, reply_id: int = 777):
    calls: list[dict] = []

    async def fake_reply(token, repo_full_name, number, comment_id, body, base_url=None):
        calls.append({"comment_id": comment_id, "body": body})
        return {"id": reply_id}

    monkeypatch.setattr(github_service, "post_reply", fake_reply)
    return calls


def configure_llm(monkeypatch, summaries: dict[int, str] | None = None):
    payload = json.dumps(FINDINGS)
    summary_payload = None
    if summaries is not None:
        summary_payload = json.dumps(
            {
                "threads": [
                    {"thread_id": thread_id, "summary": text, "drop": False}
                    for thread_id, text in summaries.items()
                ]
            }
        )

    async def generate(credentials, model, system_prompt, user_prompt, json_mode=False, **kwargs):
        if "## thread_id" in user_prompt:
            if summary_payload is None:
                raise llm_service.LLMError("summariser unavailable")
            return summary_payload
        return payload

    monkeypatch.setattr(llm_service, "generate", as_result(generate))


def seed(client, monkeypatch, comments):
    from tests.conftest import start_review

    configure(monkeypatch, json.dumps(FINDINGS), comments=comments)
    provision(client)
    return start_review(client, PR_URL, "ollama-local:llama3")


def thread_by_origin(body: dict, origin: str) -> list[dict]:
    return [thread for thread in body["threads"] if thread["origin"] == origin]


def test_existing_comments_are_imported_grouped_and_marked_external(client, monkeypatch):
    review = seed(
        client,
        monkeypatch,
        [comment(101, "This is unbounded on large tenants."), comment(102, "Agreed.", parent=101)],
    )

    imported = thread_by_origin(review, "GITHUB_EXISTING")
    assert len(imported) == 1
    thread = imported[0]
    assert thread["github_root_comment_id"] == 101
    assert thread["original_author"] == "octocat"
    assert thread["current_round"] == 1
    assert thread["thread_status"] == "active"
    assert thread["file_path"] == PATH
    assert thread["line_number"] == 11
    assert [message["content"] for message in thread["messages"]] == [
        "This is unbounded on large tenants.",
        "Agreed.",
    ]
    assert all(message["is_external"] for message in thread["messages"])
    assert thread["rounds"][0]["round_number"] == 1
    assert thread["rounds"][0]["status"] == "published"
    assert thread["rounds"][0]["inbound_body"] == "This is unbounded on large tenants."

    # The AI findings are still created and anchored, but start undecided.
    ai = thread_by_origin(review, "AI_GENERATED")
    assert len(ai) == 2
    assert all(item["rounds"][0]["status"] == "drafting" for item in ai)
    assert ai[0]["rounds"][0]["inbound_github_comment_id"] is None


def test_group_comments_walks_reply_chains_to_the_root():
    threads = group_comments(
        [
            comment(1, "root"),
            comment(2, "first reply", parent=1),
            comment(3, "reply to the reply", parent=2),
        ]
    )
    assert len(threads) == 1
    assert threads[0].root_id == 1
    assert [reply.id for reply in threads[0].replies] == [2, 3]


def test_sync_opens_a_round_for_a_new_reply_and_is_idempotent(client, monkeypatch):
    review = seed(client, monkeypatch, [comment(101, "This is unbounded.")])
    items = stub_comments(monkeypatch, [comment(101, "This is unbounded.")])
    items.append(comment(102, "We cap it at 50 now.", parent=101, author="reviewer"))

    response = client.post(f"/api/reviews/{review['id']}/sync")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["new_rounds"] == 1
    assert body["new_threads"] == 0

    thread = thread_by_origin(body["review"], "GITHUB_EXISTING")[0]
    assert thread["current_round"] == 2
    assert thread["thread_status"] == "needs_response"
    opened = thread["rounds"][1]
    assert opened["round_number"] == 2
    assert opened["status"] == "drafting"
    assert opened["inbound_author"] == "reviewer"
    assert opened["inbound_body"] == "We cap it at 50 now."

    again = client.post(f"/api/reviews/{review['id']}/sync").json()
    assert (again["new_threads"], again["new_rounds"]) == (0, 0)
    assert len(thread_by_origin(again["review"], "GITHUB_EXISTING")[0]["rounds"]) == 2


def test_sync_creates_a_thread_for_a_new_top_level_comment(client, monkeypatch):
    review = seed(client, monkeypatch, [])
    stub_comments(monkeypatch, [comment(301, "Please add a test for this.", line=12)])

    body = client.post(f"/api/reviews/{review['id']}/sync").json()
    assert body["new_threads"] == 1
    created = [
        thread
        for thread in thread_by_origin(body["review"], "GITHUB_EXISTING")
        if thread["github_root_comment_id"] == 301
    ]
    assert len(created) == 1
    assert created[0]["line_number"] == 12
    assert created[0]["rounds"][0]["status"] == "published"


def test_sync_ignores_only_its_own_review_comments(client, monkeypatch):
    """Identity is the review id, not the author: the reviewer replies from the same account."""
    review = seed(client, monkeypatch, [comment(101, "Root")])
    set_review_url(review["id"], f"{PR_URL}#pullrequestreview-900")
    stub_comments(
        monkeypatch,
        [
            comment(101, "Root"),
            comment(201, "**High** — our own finding", review_id=900, author="me", line=12),
            comment(202, "Why is this a problem?", parent=101, review_id=901, author="me"),
            comment(
                301,
                "New top-level comment from the same account",
                review_id=902,
                author="me",
                line=12,
            ),
        ],
    )

    body = client.post(f"/api/reviews/{review['id']}/sync").json()
    assert (body["new_threads"], body["new_rounds"]) == (1, 1)

    roots = {
        thread["github_root_comment_id"]
        for thread in body["review"]["threads"]
        if thread["github_root_comment_id"]
    }
    assert 201 not in roots  # our own finding is never re-imported
    assert {101, 301} <= roots

    imported = next(
        thread for thread in body["review"]["threads"] if thread["github_root_comment_id"] == 101
    )
    assert imported["current_round"] == 2
    assert imported["rounds"][1]["inbound_author"] == "me"


def test_sync_heals_a_missing_root_id_and_attaches_the_reply(client, monkeypatch):
    review = accept_findings(client, seed(client, monkeypatch, []))
    stub_review_post(monkeypatch, review_id=900)
    stub_review_comments(monkeypatch, [])  # the apply-time backfill finds nothing
    assert (
        client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"}).status_code
        == 200
    )

    stored = client.get(f"/api/reviews/{review['id']}").json()
    ai = thread_by_origin(stored, "AI_GENERATED")
    assert all(thread["github_root_comment_id"] is None for thread in ai)

    stub_comments(
        monkeypatch,
        [
            comment(901, FINDINGS[0]["initialComment"], review_id=900, author="me", line=11),
            comment(902, FINDINGS[1]["initialComment"], review_id=900, author="me", line=12),
            comment(903, "Why does this matter?", parent=901, review_id=901, author="me"),
        ],
    )

    body = client.post(f"/api/reviews/{review['id']}/sync").json()
    assert (body["new_threads"], body["new_rounds"]) == (0, 1)
    healed = next(
        thread
        for thread in body["review"]["threads"]
        if thread["github_root_comment_id"] == 901
    )
    assert healed["current_round"] == 2
    assert healed["rounds"][1]["inbound_body"] == "Why does this matter?"


def test_accept_summarises_the_round_before_it_is_posted(client, monkeypatch):
    """The published reply is a rewritten comment, not the chat message pasted into GitHub."""
    review = seed(client, monkeypatch, [comment(101, "Root")])
    items = stub_comments(monkeypatch, [comment(101, "Root")])
    items.append(comment(102, "We cap it at 50 now.", parent=101, author="reviewer"))
    synced = client.post(f"/api/reviews/{review['id']}/sync").json()
    thread = thread_by_origin(synced["review"], "GITHUB_EXISTING")[0]
    round_id = thread["rounds"][1]["id"]

    async def generate(credentials, model, system_prompt, user_prompt, json_mode=False, **kwargs):
        if "Write the single GitHub comment" in system_prompt:
            return json.dumps({"summary": "**Fixed** — the query is capped at 50."})
        if "## thread_id" in user_prompt:
            raise llm_service.LLMError("summariser unavailable")
        if json_mode:
            return json.dumps(FINDINGS)
        return "Chat prose: yes, we cap it in the controller, so the scan is bounded now."

    monkeypatch.setattr(llm_service, "generate", as_result(generate))

    discussed = client.post(
        f"/api/reviews/{review['id']}/discuss",
        json={"threads": [{"thread_id": thread["id"], "message": "Is this fixed?"}]},
    )
    assert discussed.status_code == 200, discussed.text

    accepted = client.post(
        f"/api/reviews/{review['id']}/rounds/{round_id}/decision",
        json={"decision": "accept"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["warnings"] == []
    stored = thread_by_origin(accepted.json()["review"], "GITHUB_EXISTING")[0]["rounds"][1]
    assert stored["final_summary"] == "**Fixed** — the query is capped at 50."
    assert "Chat prose" not in stored["final_summary"]

    stub_review_post(monkeypatch)
    reply_calls = stub_reply(monkeypatch)
    applied = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"})
    assert applied.status_code == 200, applied.text
    assert reply_calls == [
        {"comment_id": 101, "body": "**Fixed** — the query is capped at 50."}
    ]


def test_accept_stores_the_reviewers_text_without_calling_the_model(client, monkeypatch):
    review = seed(client, monkeypatch, [comment(101, "Root")])
    ai = thread_by_origin(review, "AI_GENERATED")[0]
    round_id = ai["rounds"][0]["id"]

    calls: list[str] = []

    async def generate(credentials, model, system_prompt, user_prompt, json_mode=False, **kwargs):
        calls.append(system_prompt)
        return json.dumps(FINDINGS)

    monkeypatch.setattr(llm_service, "generate", as_result(generate))

    accepted = client.post(
        f"/api/reviews/{review['id']}/rounds/{round_id}/decision",
        json={"decision": "accept", "summary": "**Medium** — wording I chose myself."},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["warnings"] == []
    stored = thread_by_origin(accepted.json()["review"], "AI_GENERATED")[0]["rounds"][0]
    assert stored["final_summary"] == "**Medium** — wording I chose myself."
    assert calls == []  # no model call at all


def test_accept_falls_back_to_the_copilot_text_when_summarising_fails(client, monkeypatch):
    review = seed(client, monkeypatch, [comment(101, "Root")])
    ai = thread_by_origin(review, "AI_GENERATED")[0]
    round_id = ai["rounds"][0]["id"]

    async def generate(credentials, model, system_prompt, user_prompt, json_mode=False, **kwargs):
        if "Write the single GitHub comment" in system_prompt:
            raise llm_service.LLMError("provider down")
        return json.dumps(FINDINGS)

    monkeypatch.setattr(llm_service, "generate", as_result(generate))

    accepted = client.post(
        f"/api/reviews/{review['id']}/rounds/{round_id}/decision",
        json={"decision": "accept"},
    )
    assert accepted.status_code == 200, accepted.text
    assert "Could not summarise this round" in accepted.json()["warnings"][0]
    stored = thread_by_origin(accepted.json()["review"], "AI_GENERATED")[0]["rounds"][0]
    assert stored["final_summary"] == FINDINGS[0]["initialComment"]
    assert stored["status"] == "pending_apply"


def test_apply_does_not_resummarise_an_accepted_finding(client, monkeypatch):
    review = seed(client, monkeypatch, [])
    first, second = thread_by_origin(review, "AI_GENERATED")
    # Accept the second with the reviewer's own text (no model call).
    assert (
        client.post(
            f"/api/reviews/{review['id']}/rounds/{second['rounds'][0]['id']}/decision",
            json={"decision": "accept", "summary": "**Medium** — second accepted."},
        ).status_code
        == 200
    )

    async def summariser(credentials, model, system_prompt, user_prompt, json_mode=False, **kwargs):
        if "Write the single GitHub comment" in system_prompt:
            return json.dumps({"summary": "**High** — accepted wording."})
        return json.dumps(FINDINGS)

    monkeypatch.setattr(llm_service, "generate", as_result(summariser))
    accepted = client.post(
        f"/api/reviews/{review['id']}/rounds/{first['rounds'][0]['id']}/decision",
        json={"decision": "accept"},
    )
    assert accepted.status_code == 200, accepted.text

    async def explode(*args, **kwargs):
        raise llm_service.LLMError("the apply pass must not run")

    monkeypatch.setattr(llm_service, "generate", as_result(explode))
    review_calls = stub_review_post(monkeypatch)
    stub_review_comments(monkeypatch, [])

    applied = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"})
    assert applied.status_code == 200, applied.text
    bodies = {comment["line"]: comment["body"] for comment in review_calls[0]["comments"]}
    assert bodies == {11: "**High** — accepted wording.", 12: "**Medium** — second accepted."}


def test_push_back_keeps_a_finding_off_github_and_accept_restores_it(client, monkeypatch):
    review = seed(client, monkeypatch, [])
    ai = thread_by_origin(review, "AI_GENERATED")
    thread_id, round_id = ai[0]["id"], ai[0]["rounds"][0]["id"]
    # The other finding is accepted, so the apply below has exactly one comment to compare against.
    assert (
        client.post(
            f"/api/reviews/{review['id']}/rounds/{ai[1]['rounds'][0]['id']}/decision",
            json={"decision": "accept", "summary": "**Medium** — keep this one."},
        ).status_code
        == 200
    )

    def decide(decision: str) -> dict:
        response = client.post(
            f"/api/reviews/{review['id']}/rounds/{round_id}/decision",
            json={"decision": decision},
        )
        assert response.status_code == 200, response.text
        return next(
            thread for thread in response.json()["review"]["threads"] if thread["id"] == thread_id
        )

    pushed = decide("push_back")
    assert pushed["thread_status"] == "resolved"
    assert pushed["dropped"] is True
    assert pushed["rounds"][0]["status"] == "resolved_no_reply"

    accepted = decide("accept")
    assert accepted["thread_status"] == "active"
    assert accepted["dropped"] is False
    assert accepted["rounds"][0]["status"] == "pending_apply"

    assert decide("push_back")["rounds"][0]["status"] == "resolved_no_reply"
    stub_review_post(monkeypatch)
    stub_review_comments(monkeypatch, [])
    applied = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"})
    assert applied.status_code == 200, applied.text
    assert applied.json()["comments_posted"] == 1



def test_delta_apply_posts_the_review_then_only_the_new_reply(client, monkeypatch):
    review = accept_findings(client, seed(client, monkeypatch, [comment(101, "This is unbounded.")]))
    ai = thread_by_origin(review, "AI_GENERATED")
    configure_llm(monkeypatch, {thread["id"]: "**High** — bounded now." for thread in ai})
    review_calls = stub_review_post(monkeypatch)
    stub_review_comments(
        monkeypatch,
        [
            {"id": 501, "path": PATH, "line": 11, "body": "**High** — bounded now."},
            {"id": 502, "path": PATH, "line": 12, "body": "**High** — bounded now."},
        ],
    )
    reply_calls = stub_reply(monkeypatch)

    first = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"})
    assert first.status_code == 200, first.text
    assert first.json()["comments_posted"] == 2
    assert first.json()["replies_posted"] == 0
    assert len(review_calls) == 1
    assert reply_calls == []

    stored = client.get(f"/api/reviews/{review['id']}").json()
    roots = {thread["line_number"]: thread["github_root_comment_id"] for thread in stored["threads"]}
    assert roots[11] == 501 and roots[12] == 502

    items = stub_comments(monkeypatch, [comment(101, "This is unbounded.")])
    items.append(comment(102, "We cap it at 50 now.", parent=101, author="reviewer"))
    sync = client.post(f"/api/reviews/{review['id']}/sync").json()
    round_id = thread_by_origin(sync["review"], "GITHUB_EXISTING")[0]["rounds"][1]["id"]

    decided = client.post(
        f"/api/reviews/{review['id']}/rounds/{round_id}/decision",
        json={"decision": "publish", "summary": "Good catch — the limit is 50 now."},
    )
    assert decided.status_code == 200, decided.text

    second = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"})
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["comments_posted"] == 0
    assert body["replies_posted"] == 1
    assert len(review_calls) == 1  # no duplicate review
    assert reply_calls == [
        {"comment_id": 101, "body": "Good catch — the limit is 50 now."}
    ]

    thread = thread_by_origin(body["review"], "GITHUB_EXISTING")[0]
    assert thread["thread_status"] == "applied"
    assert thread["rounds"][1]["status"] == "published"
    assert thread["rounds"][1]["published_github_comment_id"] == 777

    third = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"})
    assert third.status_code == 409


def test_discussing_a_published_round_opens_a_draft_round(client, monkeypatch):
    review = accept_findings(client, seed(client, monkeypatch, [comment(101, "Root comment")]))
    thread_id = thread_by_origin(review, "GITHUB_EXISTING")[0]["id"]
    stub_review_post(monkeypatch, review_id=None)
    stub_review_comments(monkeypatch, [])
    assert client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"}).status_code == 200

    async def prose(*args, **kwargs):
        return "The cap is enforced in the controller."

    monkeypatch.setattr(llm_service, "generate", as_result(prose))
    discussed = client.post(
        f"/api/reviews/{review['id']}/discuss",
        json={"threads": [{"thread_id": thread_id, "message": "Draft a reply to the reviewer."}]},
    )
    assert discussed.status_code == 200, discussed.text
    imported = thread_by_origin(discussed.json()["review"], "GITHUB_EXISTING")[0]
    assert imported["current_round"] == 2
    assert [item["status"] for item in imported["rounds"]] == ["published", "drafting"]
    assert imported["rounds"][1]["inbound_github_comment_id"] is None
    assert [
        (message["round_number"], message["role"]) for message in imported["messages"]
    ][-2:] == [(2, "user"), (2, "assistant")]

    round_id = imported["rounds"][1]["id"]
    queued = client.post(
        f"/api/reviews/{review['id']}/rounds/{round_id}/decision",
        json={"decision": "publish"},
    )
    assert queued.status_code == 200, queued.text

    reply_calls = stub_reply(monkeypatch)
    applied = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"})
    assert applied.status_code == 200, applied.text
    assert applied.json()["replies_posted"] == 1
    assert reply_calls == [{"comment_id": 101, "body": "The cap is enforced in the controller."}]


def test_resolved_round_is_skipped_and_leaves_nothing_pending(client, monkeypatch):
    review = accept_findings(client, seed(client, monkeypatch, [comment(101, "Root")]))
    stub_review_post(monkeypatch, review_id=None)
    stub_review_comments(monkeypatch, [])
    reply_calls = stub_reply(monkeypatch)
    assert client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"}).status_code == 200

    items = stub_comments(monkeypatch, [comment(101, "Root")])
    items.append(comment(102, "This pattern is intentional.", parent=101, author="reviewer"))
    sync = client.post(f"/api/reviews/{review['id']}/sync").json()
    thread = thread_by_origin(sync["review"], "GITHUB_EXISTING")[0]
    round_id = thread["rounds"][1]["id"]

    decided = client.post(
        f"/api/reviews/{review['id']}/rounds/{round_id}/decision",
        json={"decision": "resolve"},
    ).json()
    stored = thread_by_origin(decided["review"], "GITHUB_EXISTING")[0]
    assert stored["thread_status"] == "resolved"
    assert stored["rounds"][1]["status"] == "resolved_no_reply"

    apply_again = client.post(f"/api/reviews/{review['id']}/apply", json={"event": "COMMENT"})
    assert apply_again.status_code == 409
    assert reply_calls == []


def test_publish_without_any_text_is_rejected(client, monkeypatch):
    review = seed(client, monkeypatch, [comment(101, "Root")])
    items = stub_comments(monkeypatch, [comment(101, "Root")])
    items.append(comment(102, "Reply", parent=101, author="reviewer"))
    sync = client.post(f"/api/reviews/{review['id']}/sync").json()
    round_id = thread_by_origin(sync["review"], "GITHUB_EXISTING")[0]["rounds"][1]["id"]

    response = client.post(
        f"/api/reviews/{review['id']}/rounds/{round_id}/decision",
        json={"decision": "publish"},
    )
    assert response.status_code == 422
    assert "nothing to publish" in response.json()["detail"].lower()


def test_round_from_another_review_is_404(client, monkeypatch):
    first = seed(client, monkeypatch, [comment(101, "Root")])
    items = stub_comments(monkeypatch, [comment(101, "Root")])
    items.append(comment(102, "Reply", parent=101, author="reviewer"))
    sync = client.post(f"/api/reviews/{first['id']}/sync").json()
    round_id = thread_by_origin(sync["review"], "GITHUB_EXISTING")[0]["rounds"][1]["id"]

    second = seed(client, monkeypatch, [])
    response = client.post(
        f"/api/reviews/{second['id']}/rounds/{round_id}/decision",
        json={"decision": "resolve"},
    )
    assert response.status_code == 404


def test_sync_on_a_gitlab_review_explains_it_is_github_only(client):
    import asyncio

    from app.db.session import SessionLocal
    from app.models.keys import VersionControlKey
    from app.models.review import CodeReview
    from app.services import thread_sync, vcs

    user_id = client.get("/api/auth/me").json()["id"]
    db = SessionLocal()
    try:
        review = CodeReview(user_id=user_id, pr_url=MR_URL, vcs="gitlab", status="draft")
        key = VersionControlKey(user_id=user_id, provider="gitlab", token="glpat-test")
        db.add_all([review, key])
        db.commit()
        outcome = asyncio.run(thread_sync.sync_review(db, review, key, vcs.parse_pr_url(MR_URL)))
        assert (outcome.new_threads, outcome.new_rounds) == (0, 0)
        assert "GitHub reviews only" in outcome.warnings[0]
    finally:
        db.close()


def test_pending_count_covers_findings_and_ready_replies(client, monkeypatch):
    from app.db.session import SessionLocal
    from app.models.review import CodeReview

    review = seed(client, monkeypatch, [comment(101, "Root")])
    db = SessionLocal()
    try:
        row = db.get(CodeReview, review["id"])
        assert pending_round_count(row) == 0  # nothing is accepted yet
    finally:
        db.close()

    accept_findings(client, review)
    db = SessionLocal()
    try:
        row = db.get(CodeReview, review["id"])
        assert pending_round_count(row) == 2  # two accepted, unposted AI findings
    finally:
        db.close()
