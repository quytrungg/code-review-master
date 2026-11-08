"""Two accounts must never see each other's keys, reviews or settings."""

from __future__ import annotations

import json

from tests.conftest import start_review
from tests.fixtures import MR_URL, PR_URL, create_llm_key, create_vcs_key, provision
from tests.test_review_pipeline import FINDINGS, configure


def _owner_keys(client) -> tuple[int, int]:
    vcs = create_vcs_key(client, provider="github", token="ghp-owner-token")
    llm = create_llm_key(client, provider="ollama_local", api_key=None)
    return vcs["id"], llm["id"]


def test_keys_do_not_leak_between_accounts(client, second_client):
    _clear_keys(client)
    vcs_id, llm_id = _owner_keys(client)

    assert [row["id"] for row in second_client.get("/api/keys/version-control").json()] == []
    assert [row["id"] for row in second_client.get("/api/keys/llm").json()] == []

    # Every operation by id is a 404 for the other account: ids are not probe-able.
    for method, path, payload in (
        ("PATCH", f"/api/keys/version-control/{vcs_id}", {"label": "stolen"}),
        ("DELETE", f"/api/keys/version-control/{vcs_id}", None),
        ("POST", f"/api/keys/version-control/{vcs_id}/test", None),
        ("PATCH", f"/api/keys/llm/{llm_id}", {"label": "stolen"}),
        ("DELETE", f"/api/keys/llm/{llm_id}", None),
        ("POST", f"/api/keys/llm/{llm_id}/test", None),
    ):
        response = (
            second_client.request(method, path, json=payload)
            if payload is not None
            else second_client.request(method, path)
        )
        assert response.status_code == 404, (method, path, response.text)

    # The owner still has both keys, untouched.
    assert [row["id"] for row in client.get("/api/keys/version-control").json()] == [vcs_id]
    assert client.get("/api/keys/llm").json()[0]["label"] != "stolen"


def test_settings_and_active_selection_are_per_account(client, second_client):
    vcs_id, llm_id = _owner_keys(client)
    client.put("/api/settings", json={"version_control_key_id": vcs_id, "llm_key_id": llm_id})

    owner = client.get("/api/settings").json()
    assert owner["version_control_key_id"] == vcs_id
    assert owner["needs_setup"] is False

    other = second_client.get("/api/settings").json()
    assert other["version_control_key_id"] is None
    assert other["needs_setup"] is True

    # Pointing at someone else's key id is rejected rather than silently ignored.
    stolen = second_client.put("/api/settings", json={"version_control_key_id": vcs_id})
    assert stolen.status_code == 404


def test_reviews_are_only_visible_to_their_owner(client, second_client, monkeypatch):
    configure(monkeypatch, json.dumps(FINDINGS))
    provision(client)
    review = start_review(client, PR_URL, "ollama-local:llama3")
    review_id = review["id"]

    assert [row["id"] for row in client.get("/api/reviews").json()] == [review_id]
    assert second_client.get("/api/reviews").json() == []

    assert second_client.get(f"/api/reviews/{review_id}").status_code == 404
    assert second_client.get(f"/api/reviews/{review_id}/events").status_code == 404
    assert (
        second_client.post(
            f"/api/reviews/{review_id}/discuss",
            json={"threads": [{"thread_id": review["threads"][0]["id"], "message": "hi"}]},
        ).status_code
        == 404
    )
    assert (
        second_client.post(f"/api/reviews/{review_id}/apply", json={"event": "COMMENT"}).status_code
        == 404
    )


def _clear_keys(client) -> None:
    for key in client.get("/api/keys/version-control").json():
        client.delete(f"/api/keys/version-control/{key['id']}")
    for key in client.get("/api/keys/llm").json():
        client.delete(f"/api/keys/llm/{key['id']}")


def test_a_review_uses_its_owners_credentials(client, second_client, monkeypatch):
    """The background job resolves keys through the review's owner, not whoever is logged in."""
    configure(monkeypatch, json.dumps(FINDINGS))
    _clear_keys(client)
    # Only the second account has any credentials.
    provision(second_client, vcs="gitlab", vcs_token="glpat-demo-token")

    # The owner has none, so creating a review must fail with the setup message.
    response = client.post("/api/reviews", json={"pr_url": MR_URL, "model": "ollama-local:llama3"})
    assert response.status_code == 400
    assert "token configured" in response.json()["detail"]

    # And the account that does have keys succeeds.
    created = second_client.post(
        "/api/reviews", json={"pr_url": MR_URL, "model": "ollama-local:llama3"}
    )
    assert created.status_code == 202, created.text
