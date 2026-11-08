from __future__ import annotations

from tests.fixtures import activate, create_llm_key, create_vcs_key


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_reviews_list_is_empty_initially(client):
    response = client.get("/api/reviews")
    assert response.status_code == 200
    assert response.json() == []


def test_defaults_when_nothing_is_configured(client):
    body = client.get("/api/settings").json()
    assert body["version_control_key_id"] is None
    assert body["llm_key_id"] is None
    assert body["version_control"] is None
    assert body["llm"] is None
    assert body["needs_setup"] is True


def test_version_control_key_is_masked_and_revealable(client):
    token = "ghp_1234567890abcdef"
    created = create_vcs_key(client, provider="github", token=token)
    assert created["token_masked"].startswith("ghp_")
    assert token not in str(created)

    listed = {row["id"]: row for row in client.get("/api/keys/version-control").json()}
    assert listed[created["id"]]["token_masked"] == "ghp_" + "•" * 8 + "cdef"
    assert listed[created["id"]]["token"] is None

    revealed = {
        row["id"]: row
        for row in client.get("/api/keys/version-control", params={"reveal": "true"}).json()
    }
    assert revealed[created["id"]]["token"] == token


def test_gitlab_key_keeps_its_base_url_and_is_selected(client):
    key = create_vcs_key(
        client, provider="gitlab", token="glpat-1234567890", base_url="https://gitlab.example.com/"
    )
    assert key["provider"] == "gitlab"
    activated = activate(client, version_control_key_id=key["id"])
    assert activated["version_control"]["provider"] == "gitlab"
    # Trailing slashes are normalised away.
    assert activated["version_control"]["base_url"] == "https://gitlab.example.com"


def test_unknown_version_control_provider_is_rejected(client):
    response = client.post(
        "/api/keys/version-control", json={"provider": "bitbucket", "token": "x"}
    )
    assert response.status_code == 422


def test_llm_key_requires_a_secret_except_for_local_ollama(client):
    missing = client.post("/api/keys/llm", json={"provider": "claude"})
    assert missing.status_code == 422

    local = create_llm_key(client, provider="ollama_local", base_url="http://localhost:11434")
    assert local["api_key_masked"] is None

    openai = create_llm_key(client, provider="openai", api_key="sk-openai-1234567890")
    assert openai["provider"] == "openai"


def test_activation_requires_both_families_before_setup_is_complete(client):
    vcs = create_vcs_key(client)
    partial = activate(client, version_control_key_id=vcs["id"])
    assert partial["needs_setup"] is True

    llm = create_llm_key(client, provider="claude", api_key="sk-ant-test-123456")
    complete = activate(client, llm_key_id=llm["id"])
    assert complete["needs_setup"] is False
    assert complete["llm"]["provider"] == "claude"


def test_explicit_null_clears_the_active_selection(client):
    vcs = create_vcs_key(client)
    llm = create_llm_key(client, provider="ollama_local")
    activate(client, version_control_key_id=vcs["id"], llm_key_id=llm["id"])

    cleared = client.put("/api/settings", json={"llm_key_id": None})
    assert cleared.status_code == 200
    assert cleared.json()["llm_key_id"] is None
    assert cleared.json()["needs_setup"] is True
    # The key itself is untouched.
    remaining = {row["id"] for row in client.get("/api/keys/llm").json()}
    assert llm["id"] in remaining


def test_deleting_the_active_key_clears_the_pointer(client):
    vcs = create_vcs_key(client)
    activate(client, version_control_key_id=vcs["id"])

    assert client.delete(f"/api/keys/version-control/{vcs['id']}").status_code == 204
    body = client.get("/api/settings").json()
    assert body["version_control_key_id"] is None
    assert body["needs_setup"] is True
    remaining = {row["id"] for row in client.get("/api/keys/version-control").json()}
    assert vcs["id"] not in remaining


def test_activating_an_unknown_key_is_404(client):
    response = client.put("/api/settings", json={"llm_key_id": 999})
    assert response.status_code == 404


def test_connection_test_without_keys_reports_failure_not_5xx(client):
    response = client.post(
        "/api/settings/test-connection", json={"targets": ["version_control", "llm"]}
    )
    assert response.status_code == 200
    results = {entry["target"]: entry for entry in response.json()["results"]}
    assert results["version_control"]["ok"] is False
    assert results["llm"]["ok"] is False


def test_unknown_connection_target_is_422(client):
    response = client.post("/api/settings/test-connection", json={"targets": ["gitlab"]})
    assert response.status_code == 422


def test_key_test_endpoint_uses_the_provider_probe(client, monkeypatch):
    from app.services import github_service

    async def accept(token, base_url=None):
        return True, "Authenticated as octocat", {"login": "octocat"}

    monkeypatch.setattr(github_service, "verify_token", accept)
    key = create_vcs_key(client)

    response = client.post(f"/api/keys/version-control/{key['id']}/test")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "detail": "Authenticated as octocat",
        "metadata": {"login": "octocat"},
    }


def test_llm_key_base_url_is_used_for_the_probe(client, monkeypatch):
    from app.services import llm_service

    seen: dict[str, str] = {}

    async def probe(base_url, api_key=None, timeout=10.0, label="Ollama"):
        seen["base_url"] = base_url
        seen["api_key"] = api_key or ""
        return True, "1 model(s) available", {"models": ["m"]}

    monkeypatch.setattr(llm_service, "probe_ollama", probe)
    key = create_llm_key(
        client, provider="ollama_cloud", api_key="cloud-key", base_url="https://ollama.test"
    )

    response = client.post(f"/api/keys/llm/{key['id']}/test")
    assert response.json()["ok"] is True
    assert seen["base_url"] == "https://ollama.test"
    assert seen["api_key"] == "cloud-key"
