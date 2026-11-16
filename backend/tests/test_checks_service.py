from __future__ import annotations

import json

from app.services import checks_service, llm_service
from app.services.diff_parser import parse_diff, reviewable_files
from app.services.review_pipeline import AnchoredFinding, dedupe_findings
from app.services.pull_request import PullRequestInfo
from tests.fixtures import PR_URL, llm_result, provision

TOKEN = "ghp_" + "a" * 36

SECRET_DIFF = f"""diff --git a/src/config.py b/src/config.py
--- a/src/config.py
+++ b/src/config.py
@@ -1,3 +1,4 @@
 import os
+GITHUB_TOKEN = "{TOKEN}"
+<<<<<<< HEAD
 x = 1
"""

FIXTURE_DIFF = f"""diff --git a/tests/fixtures/keys.py b/tests/fixtures/keys.py
--- a/tests/fixtures/keys.py
+++ b/tests/fixtures/keys.py
@@ -1,2 +1,3 @@
 # fake credentials for tests
+GITHUB_TOKEN = "{TOKEN}"
 x = 1
"""

TEST_DIFF = """diff --git a/src/__tests__/auth.test.ts b/src/__tests__/auth.test.ts
--- a/src/__tests__/auth.test.ts
+++ b/src/__tests__/auth.test.ts
@@ -1,3 +1,4 @@
 describe("auth", () => {
+  it.only("works", () => {
   expect(true).toBe(true);
 });
}
"""


def _packs(*ids: str):
    return checks_service.enabled_packs(list(ids))


def test_scan_finds_a_known_token_on_the_added_line():
    files = reviewable_files(parse_diff(SECRET_DIFF))
    hits = checks_service.scan(files, _packs("secrets"))

    assert len(hits) == 1
    assert hits[0].path == "src/config.py"
    assert hits[0].line_number == 2
    assert hits[0].comment.startswith("Critical —")
    assert hits[0].origin == "CHECK"
    assert hits[0].pack == "secrets"


def test_hygiene_pack_finds_conflict_markers_and_focused_tests():
    files = reviewable_files(parse_diff(SECRET_DIFF + TEST_DIFF))
    hits = checks_service.scan(files, _packs("hygiene"))

    rules = {(hit.path, hit.rule) for hit in hits}
    assert ("src/config.py", "conflict-marker") in rules
    assert ("src/__tests__/auth.test.ts", "focused-test") in rules
    assert len(hits) == 2


def test_fixture_paths_are_left_alone_by_the_secret_pack():
    files = reviewable_files(parse_diff(FIXTURE_DIFF))
    assert checks_service.scan(files, _packs("secrets")) == []


def test_pack_cap_stops_reporting_and_warns():
    lines = "".join(
        f'+KEY_{index} = "{"ghp_" + "b" * 36}"\n' for index in range(3)
    )
    diff = (
        "diff --git a/src/keys.py b/src/keys.py\n--- a/src/keys.py\n+++ b/src/keys.py\n"
        f"@@ -0,0 +1,{3} @@\n{lines}"
    )
    files = reviewable_files(parse_diff(diff))
    pack = checks_service.Pack(
        id="secrets", label="Secrets", description="", max_per_review=2,
        rules=checks_service.PACKS[0].rules,
    )
    warnings: list[str] = []
    hits = checks_service.scan(files, [pack], warnings)
    assert len(hits) == 2
    assert any("more than 2" in warning for warning in warnings)


def test_a_check_wins_the_shared_line_in_dedupe():
    warnings: list[str] = []
    check = AnchoredFinding("a.py", 4, "", "Critical — token", origin="CHECK")
    model = AnchoredFinding("a.py", 4, "", "A much longer model explanation", origin="AI_GENERATED")
    kept = dedupe_findings([check, model], warnings)
    assert [item.origin for item in kept] == ["CHECK"]
    assert warnings and "duplicate" in warnings[0]


def _fake_pr(token, owner, repo, number, base_url=None):
    return PullRequestInfo(
        vcs="github",
        project="octo/example",
        number=number,
        title="Add a token",
        state="open",
        draft=False,
        head_sha="abc123sha",
        base_sha="base123sha",
        start_sha="base123sha",
        base_ref="main",
        html_url=PR_URL,
        author="octocat",
        body="",
        additions=2,
        deletions=0,
        changed_files=1,
    )


def test_pipeline_persists_a_check_thread_without_an_extra_model_call(client, monkeypatch):
    from app.db.session import SessionLocal
    from tests.conftest import start_review

    prompts: list[str] = []

    async def generate(*args, **kwargs):
        prompts.append(args[3])
        return llm_result(json.dumps({"verdict": "APPROVE", "confidence": 90, "findings": []}))

    async def fetch_pr(token, owner, repo, number, base_url=None):
        return _fake_pr(token, owner, repo, number, base_url)

    async def fetch_diff(token, owner, repo, number, base_url=None):
        return SECRET_DIFF

    async def no_comments(token, repo_full_name, number, base_url=None):
        return []

    monkeypatch.setattr(llm_service, "generate", generate)
    monkeypatch.setattr("app.services.github_service.fetch_pr", fetch_pr)
    monkeypatch.setattr("app.services.github_service.fetch_diff", fetch_diff)
    monkeypatch.setattr("app.services.github_service.fetch_review_comments", no_comments)
    provision(client)

    settings = client.put("/api/settings", json={"check_packs": ["secrets", "hygiene"]})
    assert settings.status_code == 200, settings.text
    assert settings.json()["check_packs"] == ["secrets", "hygiene"]

    body = start_review(client, PR_URL, "ollama-local:llama3")

    assert body["status"] == "draft"
    assert body["thread_count"] == 2  # the token and the conflict marker
    checks = [thread for thread in body["threads"] if thread["origin"] == "CHECK"]
    assert len(checks) == 2
    assert any("Deterministic checks: 1 secrets, 1 hygiene." == note for note in body["warnings"])
    # The model saw the deterministic hits and was told not to repeat them.
    assert prompts and "src/config.py:2" in prompts[0]
    assert "Do not repeat them" in prompts[0]
    # One model call for the whole diff: the checks themselves cost no tokens.
    assert len(prompts) == 1


def test_packs_are_off_until_enabled(client, monkeypatch):
    from tests.conftest import start_review

    calls: list[int] = []

    async def generate(*args, **kwargs):
        calls.append(1)
        return llm_result(json.dumps({"verdict": "APPROVE", "confidence": 90, "findings": []}))

    async def fetch_pr(token, owner, repo, number, base_url=None):
        return _fake_pr(token, owner, repo, number, base_url)

    async def fetch_diff(token, owner, repo, number, base_url=None):
        return SECRET_DIFF

    async def no_comments(token, repo_full_name, number, base_url=None):
        return []

    monkeypatch.setattr(llm_service, "generate", generate)
    monkeypatch.setattr("app.services.github_service.fetch_pr", fetch_pr)
    monkeypatch.setattr("app.services.github_service.fetch_diff", fetch_diff)
    monkeypatch.setattr("app.services.github_service.fetch_review_comments", no_comments)
    provision(client)

    assert client.get("/api/settings").json()["check_packs"] == []
    body = start_review(client, PR_URL, "ollama-local:llama3")
    assert body["thread_count"] == 0
    assert len(calls) == 1


def test_unknown_pack_is_rejected(client):
    response = client.put("/api/settings", json={"check_packs": ["lint"]})
    assert response.status_code == 422
    assert "Unknown check pack" in response.json()["detail"]
    assert client.get("/api/settings").json()["check_packs"] == []


def test_registry_is_exposed_for_the_settings_page(client):
    body = client.get("/api/settings").json()
    ids = [pack["id"] for pack in body["check_pack_registry"]]
    assert ids == ["secrets", "hygiene"]
    assert all(pack["description"] for pack in body["check_pack_registry"])
