"""The PR inbox: sync aggregation, turn-taking, quick reviews, ownership, guards, polish.

GitHub is stubbed at the service boundary — `app.services.github_inbox_service.github_service.*`
— so these tests exercise the real routes, ownership checks, upserts and turn-taking logic with
no network.
"""

from __future__ import annotations

from tests.fixtures import PR_URL, as_result, provision

SECOND_PR_URL = "https://github.com/other/lib/pull/5"
T0 = "2026-11-01T10:00:00Z"


def _item(url, *, title="A change", author="bob", updated="2026-11-10T10:00:00Z", gid=1):
    return {
        "id": gid,
        "html_url": url,
        "title": title,
        "user": {"login": author, "avatar_url": "https://avatars.example/u/bob"},
        "updated_at": updated,
        "pull_request": {"html_url": url},
    }


def _review(state, author="alice", at=T0):
    return {"state": state, "user": {"login": author}, "submitted_at": at}


def _comment(author, at):
    return {"user": {"login": author}, "created_at": at}


def stub_github(
    monkeypatch,
    *,
    items=None,
    teams=None,
    reviews=None,
    inline=None,
    conversation=None,
):
    """Replace every GitHub boundary function the inbox calls; returns the recorded requests."""
    from app.services import github_service

    recorded = {"queries": [], "posted": []}

    async def verify_token(token, base_url=None):
        return True, "Authenticated as alice", {"login": "alice"}

    async def fetch_teams(token, base_url=None):
        return list(teams or [])

    async def search_open_prs(token, query, base_url=None):
        recorded["queries"].append(query)
        return list(items or [])

    async def fetch_pull_reviews(token, full_name, number, base_url=None):
        return list(reviews or [])

    async def fetch_review_comments(token, full_name, number, base_url=None):
        return list(inline or [])

    async def fetch_issue_comments(token, full_name, number, base_url=None):
        return list(conversation or [])

    async def post_review(token, full_name, number, payload, base_url=None):
        recorded["posted"].append({"repo": full_name, "number": number, "payload": payload})
        return {"id": 7}

    async def offline(token, *args, **kwargs):
        # Inbox tests never exercise real ingestion; fail fast instead of hitting the network.
        raise github_service.GitHubError("offline in tests")

    monkeypatch.setattr(github_service, "verify_token", verify_token)
    monkeypatch.setattr(github_service, "fetch_teams", fetch_teams)
    monkeypatch.setattr(github_service, "search_open_prs", search_open_prs)
    monkeypatch.setattr(github_service, "fetch_pull_reviews", fetch_pull_reviews)
    monkeypatch.setattr(github_service, "fetch_review_comments", fetch_review_comments)
    monkeypatch.setattr(github_service, "fetch_issue_comments", fetch_issue_comments)
    monkeypatch.setattr(github_service, "post_review", post_review)
    monkeypatch.setattr(github_service, "fetch_pr", offline)
    monkeypatch.setattr(github_service, "fetch_diff", offline)
    return recorded


def reset_keys(client):
    for key in client.get("/api/keys/version-control").json():
        client.delete(f"/api/keys/version-control/{key['id']}")
    for key in client.get("/api/keys/llm").json():
        client.delete(f"/api/keys/llm/{key['id']}")


def test_list_requires_session(anon_client):
    assert anon_client.get("/api/inbox").status_code == 401
    assert anon_client.post("/api/inbox/sync").status_code == 401
    assert anon_client.post("/api/inbox/quick-review", json={}).status_code == 401


def test_sync_without_github_key_says_settings(client):
    reset_keys(client)
    response = client.post("/api/inbox/sync")
    assert response.status_code == 422, response.text
    assert "Settings" in response.json()["detail"]


def test_sync_caches_and_dedupes(client, monkeypatch):
    provision(client)
    duplicate = _item(PR_URL)
    recorded = stub_github(
        monkeypatch,
        items=[duplicate, duplicate, _item(SECOND_PR_URL, gid=3)],
    )

    response = client.post("/api/inbox/sync")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["disappeared"] == 0
    assert body["warnings"] == []
    urls = [item["pr_url"] for item in body["items"]]
    assert urls == [SECOND_PR_URL, PR_URL] or sorted(urls) == sorted({PR_URL, SECOND_PR_URL})
    assert len(set(urls)) == 2
    assert all(item["status"] == "needs_review" for item in body["items"])
    assert any("review-requested:alice" in query for query in recorded["queries"])
    assert any("commenter:alice" in query for query in recorded["queries"])


def test_sync_queries_teams(client, monkeypatch):
    provision(client)
    recorded = stub_github(
        monkeypatch, teams=[{"slug": "apex", "organization": {"login": "acme"}}], items=[]
    )
    response = client.post("/api/inbox/sync")
    assert response.status_code == 200, response.text
    assert any("team-review-requested:acme/apex" in query for query in recorded["queries"])


def test_status_from_latest_own_review(client, monkeypatch):
    provision(client)
    stub_github(monkeypatch, items=[_item(PR_URL)], reviews=[_review("CHANGES_REQUESTED")])
    item = client.post("/api/inbox/sync").json()["items"][0]
    assert item["status"] == "request_changed"
    assert item["last_user_action_at"] == T0


def test_comment_only_marks_commented(client, monkeypatch):
    provision(client)
    stub_github(monkeypatch, items=[_item(PR_URL)], inline=[_comment("alice", "2026-11-02T08:00:00Z")])
    item = client.post("/api/inbox/sync").json()["items"][0]
    assert item["status"] == "commented"
    assert item["last_user_action_at"] == "2026-11-02T08:00:00Z"


def test_inbound_reply_reverts_to_needs_review(client, monkeypatch):
    provision(client)
    stub_github(
        monkeypatch,
        items=[_item(PR_URL)],
        reviews=[_review("APPROVED", at=T0)],
        conversation=[
            _comment("bob", "2026-11-02T09:00:00Z"),
            _comment("carol", "2026-11-03T11:00:00Z"),
        ],
    )
    item = client.post("/api/inbox/sync").json()["items"][0]
    assert item["status"] == "needs_review"
    assert item["has_unread_replies"] is True
    assert item["unread_replies_count"] == 2

    listed = client.get("/api/inbox", params={"unread": "true"})
    assert listed.status_code == 200, listed.text
    assert [row["pr_url"] for row in listed.json()] == [PR_URL]


def test_own_reply_after_review_stays_approved(client, monkeypatch):
    provision(client)
    stub_github(
        monkeypatch,
        items=[_item(PR_URL)],
        reviews=[_review("APPROVED", at=T0)],
        conversation=[_comment("alice", "2026-11-02T09:00:00Z")],
    )
    item = client.post("/api/inbox/sync").json()["items"][0]
    assert item["status"] == "approved"
    assert item["has_unread_replies"] is False


def test_sync_drops_closed_prs(client, monkeypatch):
    provision(client)
    stub_github(monkeypatch, items=[_item(PR_URL)])
    assert client.post("/api/inbox/sync").json()["items"]

    stub_github(monkeypatch, items=[])
    body = client.post("/api/inbox/sync").json()
    assert body["items"] == []
    assert body["disappeared"] == 1


def test_sync_links_existing_review(client, monkeypatch):
    provision(client)
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.review import CodeReview
    from app.models.user import User

    db = SessionLocal()
    try:
        user = db.scalars(select(User).where(User.email == "tester@example.com")).first()
        assert user is not None
        review = CodeReview(user_id=user.id, pr_url=PR_URL)
        db.add(review)
        db.commit()
        review_id = review.id
    finally:
        db.close()

    stub_github(monkeypatch, items=[_item(PR_URL)])
    item = client.post("/api/inbox/sync").json()["items"][0]
    assert item["linked_review_id"] == review_id


def test_inbox_filters(client, monkeypatch):
    provision(client)
    stub_github(monkeypatch, items=[_item(PR_URL), _item(SECOND_PR_URL, gid=9)])
    client.post("/api/inbox/sync")

    by_repo = client.get("/api/inbox", params={"repo": "octo/example"})
    assert [row["pr_url"] for row in by_repo.json()] == [PR_URL]
    assert len(client.get("/api/inbox", params={"status": "needs_review"}).json()) == 2
    assert client.get("/api/inbox", params={"status": "nonsense"}).status_code == 422
    assert client.get("/api/inbox", params={"repo": "nonsense"}).status_code == 422


def test_quick_review_posts_and_resets(client, monkeypatch):
    provision(client)
    posted = stub_github(
        monkeypatch,
        items=[_item(PR_URL)],
        reviews=[_review("COMMENTED", at=T0)],
        conversation=[_comment("bob", "2026-11-02T09:00:00Z")],
    )
    item = client.post("/api/inbox/sync").json()["items"][0]
    assert item["has_unread_replies"] is True

    response = client.post(
        "/api/inbox/quick-review",
        json={"cached_pr_id": item["id"], "event": "REQUEST_CHANGES", "body": "Please add tests."},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["status"] == "request_changed"
    assert updated["has_unread_replies"] is False
    assert updated["unread_replies_count"] == 0
    assert updated["last_user_action_at"] is not None
    assert posted["posted"] == [
        {
            "repo": "octo/example",
            "number": 123,
            "payload": {"event": "REQUEST_CHANGES", "body": "Please add tests."},
        }
    ]


def test_quick_review_approve_omits_empty_body(client, monkeypatch):
    provision(client)
    posted = stub_github(monkeypatch, items=[_item(PR_URL)])
    item = client.post("/api/inbox/sync").json()["items"][0]
    response = client.post(
        "/api/inbox/quick-review", json={"cached_pr_id": item["id"], "event": "APPROVE"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
    assert posted["posted"][0]["payload"] == {"event": "APPROVE"}


def test_quick_review_guards(client, monkeypatch):
    provision(client)
    stub_github(monkeypatch, items=[_item(PR_URL)])
    item = client.post("/api/inbox/sync").json()["items"][0]

    missing_body = client.post(
        "/api/inbox/quick-review", json={"cached_pr_id": item["id"], "event": "REQUEST_CHANGES"}
    )
    assert missing_body.status_code == 422
    unknown = client.post(
        "/api/inbox/quick-review", json={"cached_pr_id": item["id"], "event": "BOGUS"}
    )
    assert unknown.status_code == 422


def test_quick_review_ownership(client, second_client, monkeypatch):
    provision(client)
    stub_github(monkeypatch, items=[_item(PR_URL)])
    item = client.post("/api/inbox/sync").json()["items"][0]

    provision(second_client)
    # The other account posts against the first account's cached id: a 404, never a 403.
    response = second_client.post(
        "/api/inbox/quick-review", json={"cached_pr_id": item["id"], "event": "APPROVE"}
    )
    assert response.status_code == 404, response.text
    assert second_client.get("/api/inbox").json() == []
    # The isolation suite asserts the second account holds no keys: leave no residue behind.
    reset_keys(second_client)


def test_polish_rewrites_with_active_model(client, monkeypatch):
    provision(client, default_model="llama3")
    from app.services import llm_service

    seen = {}

    def responder(credentials, model, system_prompt, user_prompt, **kwargs):
        seen["model"] = model.id
        seen["prompt"] = user_prompt
        return "A clearer comment."

    monkeypatch.setattr(llm_service, "generate", as_result(responder))
    response = client.post("/api/inbox/polish", json={"text": "this code bad"})
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "A clearer comment."
    assert seen["model"] == "ollama-local:llama3"
    assert "this code bad" in seen["prompt"]


def test_polish_without_model_key(client):
    reset_keys(client)
    response = client.post("/api/inbox/polish", json={"text": "hello"})
    assert response.status_code == 422
    assert "Settings" in response.json()["detail"]


def test_sync_includes_authored_and_assigned_prs(client, monkeypatch):
    provision(client)
    own = dict(_item("https://github.com/octo/own/pull/1", gid=11), user={"login": "alice"})
    assigned = dict(
        _item("https://github.com/octo/lib/pull/9", gid=12), assignees=[{"login": "alice"}]
    )
    recorded = stub_github(monkeypatch, items=[_item(PR_URL), own, assigned])

    body = client.post("/api/inbox/sync").json()
    by_url = {item["pr_url"]: item for item in body["items"]}
    assert by_url[PR_URL]["involvement"] == "reviewer"
    assert by_url["https://github.com/octo/own/pull/1"]["involvement"] == "author"
    assert by_url["https://github.com/octo/lib/pull/9"]["involvement"] == "assignee"
    assert any("author:alice" in query for query in recorded["queries"])
    assert any("assignee:alice" in query for query in recorded["queries"])


def test_authored_pr_replies_rearm_needs_review(client, monkeypatch):
    provision(client)
    own = dict(_item(PR_URL), user={"login": "alice"})
    stub_github(
        monkeypatch,
        items=[own],
        conversation=[
            _comment("alice", T0),
            _comment("bob", "2026-11-02T09:00:00Z"),
        ],
    )
    item = client.post("/api/inbox/sync").json()["items"][0]
    # On an authored PR, needs_review means "someone replied to your PR — your turn".
    assert item["involvement"] == "author"
    assert item["status"] == "needs_review"
    assert item["unread_replies_count"] == 1


def test_authored_pr_matching_reviewer_query_dedupes(client, monkeypatch):
    provision(client)
    own = dict(_item(PR_URL), user={"login": "alice"})
    stub_github(monkeypatch, items=[own, own])
    items = client.post("/api/inbox/sync").json()["items"]
    assert len(items) == 1
    assert items[0]["involvement"] == "author"


def test_creating_review_links_inbox_row_without_sync(client, monkeypatch):
    provision(client)
    stub_github(monkeypatch, items=[_item(PR_URL)])
    item = client.post("/api/inbox/sync").json()["items"][0]
    assert item["linked_review_id"] is None

    # Review creation stamps the link immediately; no sync is needed.
    created = client.post("/api/reviews", json={"pr_url": PR_URL, "model": "ollama-local:llama3"})
    assert created.status_code == 202, created.text
    review_id = created.json()["id"]

    refreshed = client.get("/api/inbox").json()
    assert refreshed[0]["linked_review_id"] == review_id
