"""Multi-pass review: fan-out, merge, dedupe, cap, verdict pass and partial failure.

The provider is stubbed one level below `llm_service.generate` (at `_generate_ollama`), so the real
wrapper — prompts, ledger, purpose — runs and the `llm_calls` rows these tests assert on are the ones
the pipeline actually wrote.
"""

from __future__ import annotations

import json
import re

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.llm_call import LLMCall, LLMPurpose
from app.services import github_service, llm_service
from app.services.pull_request import PullRequestInfo
from tests.fixtures import PR_URL, llm_result, provision
from tests.test_review_units import build_diff

FILE_RE = re.compile(r"^## File: (?P<path>\S+)", re.MULTILINE)
LINE_RE = re.compile(r"^\s*(?P<number>\d+) \+", re.MULTILINE)
VERDICT_MARKER = "This change has already been reviewed"


def fake_fetch_pr(token, owner, repo, number, base_url=None):
    return PullRequestInfo(
        vcs="github",
        project=f"{owner}/{repo}",
        number=number,
        title="Rewrite the ingest",
        state="open",
        draft=False,
        head_sha="abc123sha",
        base_sha="base123sha",
        start_sha="base123sha",
        base_ref="main",
        html_url=PR_URL,
        author="octocat",
        body="",
        additions=0,
        deletions=0,
        changed_files=1,
    )


async def fake_fetch_pr_async(token, owner, repo, number, base_url=None):
    return fake_fetch_pr(token, owner, repo, number, base_url)


def configure(monkeypatch, diff_text: str, *, responder=None, comments=None):
    """Stub GitHub and the Ollama transport; every provider call is appended to `calls`."""
    calls: list[dict] = []

    async def fetch_diff(token, owner, repo, number, base_url=None):
        return diff_text

    async def fetch_comments(token, repo_full_name, number, base_url=None):
        return list(comments or [])

    async def generate_ollama(
        provider, base_url, headers, name, system_prompt, user_prompt, config, json_mode=False
    ):
        calls.append({"prompt": user_prompt})
        text = responder(user_prompt, len(calls)) if responder else default_findings(user_prompt)
        return llm_result(text, provider="ollama-local", model=name)

    monkeypatch.setattr(github_service, "fetch_pr", fake_fetch_pr_async)
    monkeypatch.setattr(github_service, "fetch_diff", fetch_diff)
    monkeypatch.setattr(github_service, "fetch_review_comments", fetch_comments)
    monkeypatch.setattr(llm_service, "_generate_ollama", generate_ollama)
    return calls


def default_findings(prompt: str) -> str:
    """One finding per file the prompt shows, anchored to that file's first numbered line."""
    findings = []
    for block in re.split(r"(?=^## File: )", prompt, flags=re.MULTILINE):
        head = FILE_RE.search(block)
        numbered = LINE_RE.search(block)
        if head is None or numbered is None:
            continue
        findings.append(
            {
                "filePath": head.group("path"),
                "lineNumber": int(numbered.group("number")),
                "diffHunk": "",
                "initialComment": f"**Medium** — `{head.group('path')}` needs a guard.",
            }
        )
    return json.dumps({"verdict": "COMMENT", "confidence": 55, "findings": findings})


def finding(path: str, line: int, comment: str) -> dict:
    return {"filePath": path, "lineNumber": line, "diffHunk": "", "initialComment": comment}


def verdict_payload(verdict="REQUEST_CHANGES", confidence=77) -> str:
    return json.dumps({"verdict": verdict, "confidence": confidence, "rationale": "merged parts"})


def parts(calls: list[dict]) -> list[dict]:
    return [call for call in calls if VERDICT_MARKER not in call["prompt"]]


def start(client):
    from tests.conftest import start_review

    return start_review(client, PR_URL, "ollama-local:llama3")


def ledger_counts(review_id: int) -> dict[str, int]:
    with SessionLocal() as db:
        rows = db.execute(
            select(LLMCall.purpose, func.count())
            .where(LLMCall.review_id == review_id)
            .group_by(LLMCall.purpose)
        ).all()
    return {purpose: count for purpose, count in rows}


def test_a_small_diff_is_still_exactly_one_call(client, monkeypatch):
    calls = configure(monkeypatch, build_diff(1, lines=20))
    provision(client)

    body = start(client)

    assert body["status"] == "draft"
    assert len(calls) == 1
    assert "part 1 of" not in calls[0]["prompt"]
    # The single call's own opinion is used; no verdict pass is made.
    assert body["suggested_verdict"] == "COMMENT"
    assert body["confidence_percentage"] == 55
    assert ledger_counts(body["id"]) == {LLMPurpose.INGEST: 1}


def test_a_large_diff_is_reviewed_in_parts_and_every_finding_is_anchored(client, monkeypatch):
    diff_text = build_diff(16, lines=100)
    file_count = diff_text.count("diff --git ")

    def responder(prompt: str, _index: int) -> str:
        return verdict_payload() if VERDICT_MARKER in prompt else default_findings(prompt)

    calls = configure(monkeypatch, diff_text, responder=responder)
    provision(client)

    body = start(client)

    ingest = parts(calls)
    assert len(ingest) >= 3
    assert body["status"] == "draft"
    assert body["thread_count"] == file_count
    assert all(thread["line_number"] == 1 for thread in body["threads"])
    assert all(thread["diff_hunk"] for thread in body["threads"])
    # Every part knew where it sat in the split and which files it owned.
    for index, call in enumerate(ingest, start=1):
        assert f"- This prompt covers part {index} of {len(ingest)} of the change" in call["prompt"]
        assert call["prompt"].count("## File: ") < file_count
    # No part was truncated, so no truncation warning was recorded.
    assert not any("truncated" in note for note in body["warnings"])
    # The merged findings get one dedicated opinion pass.
    assert body["suggested_verdict"] == "REQUEST_CHANGES"
    assert body["confidence_percentage"] == 77
    counts = ledger_counts(body["id"])
    assert counts[LLMPurpose.INGEST] == len(ingest)
    assert counts[LLMPurpose.VERDICT] == 1


def test_the_same_finding_from_two_parts_is_stored_once_with_the_longer_body(client, monkeypatch):
    diff_text = build_diff(16, lines=100)
    shared = "**High** — `compute` swallows the timeout."

    def responder(prompt: str, index: int) -> str:
        if VERDICT_MARKER in prompt:
            return verdict_payload()
        comment = shared if index == 1 else shared + " Name the exception in the log."
        return json.dumps(
            {
                "verdict": "COMMENT",
                "confidence": 50,
                "findings": [finding("app/services/mod_00.py", 1, comment)],
            }
        )

    configure(monkeypatch, diff_text, responder=responder)
    provision(client)

    body = start(client)

    assert body["thread_count"] == 1
    assert body["threads"][0]["messages"][0]["content"].endswith("Name the exception in the log.")
    assert any("duplicate finding" in note for note in body["warnings"])


def test_the_finding_cap_drops_the_lowest_severity_first(client, monkeypatch):
    diff_text = build_diff(16, lines=100)
    report = [
        finding("app/services/mod_00.py", 1, "**Low** — nit"),
        finding("app/services/mod_01.py", 2, "**Critical** — boom"),
        finding("app/services/mod_02.py", 3, "**High** — leak"),
    ]

    def responder(prompt: str, _index: int) -> str:
        if VERDICT_MARKER in prompt:
            return verdict_payload()
        return json.dumps({"verdict": "COMMENT", "confidence": 50, "findings": report})

    monkeypatch.setenv("REVIEW_MAX_FINDINGS", "2")
    get_settings.cache_clear()
    try:
        configure(monkeypatch, diff_text, responder=responder)
        provision(client)
        body = start(client)
    finally:
        monkeypatch.delenv("REVIEW_MAX_FINDINGS")
        get_settings.cache_clear()

    assert body["thread_count"] == 2
    kept = {thread["file_path"] for thread in body["threads"]}
    assert kept == {"app/services/mod_01.py", "app/services/mod_02.py"}
    assert any("review cap" in note for note in body["warnings"])


def test_one_failed_part_leaves_a_draft_with_the_findings_that_landed(client, monkeypatch):
    diff_text = build_diff(16, lines=100)

    def responder(prompt: str, _index: int) -> str:
        if VERDICT_MARKER in prompt:
            return verdict_payload()
        if "- This prompt covers part 2 of" in prompt:
            raise llm_service.LLMError("Ollama returned HTTP 500")
        return default_findings(prompt)

    calls = configure(monkeypatch, diff_text, responder=responder)
    provision(client)

    body = start(client)

    ingest = parts(calls)
    assert len(ingest) >= 3
    assert body["status"] == "draft"
    assert body["thread_count"] > 0
    assert any("Part 2 of" in note and "could not be reviewed" in note for note in body["warnings"])

    failed_prompt = next(
        call["prompt"] for call in ingest if "- This prompt covers part 2 of" in call["prompt"]
    )
    failed_paths = set(FILE_RE.findall(failed_prompt))
    assert failed_paths
    assert {thread["file_path"] for thread in body["threads"]}.isdisjoint(failed_paths)


def test_every_part_failing_fails_the_review(client, monkeypatch):
    diff_text = build_diff(16, lines=100)

    def responder(prompt: str, _index: int) -> str:
        raise llm_service.LLMError("Ollama is not running")

    configure(monkeypatch, diff_text, responder=responder)
    provision(client)

    body = start(client)

    assert body["status"] == "failed"
    assert "Ollama is not running" in body["error"]
    assert body["threads"] == []


def test_a_multi_part_review_with_no_findings_still_gets_an_opinion(client, monkeypatch):
    diff_text = build_diff(16, lines=100)

    def responder(prompt: str, _index: int) -> str:
        if VERDICT_MARKER in prompt:
            assert "# Review state — 0 finding(s)" in prompt
            return verdict_payload("APPROVE", 90)
        return json.dumps({"verdict": "APPROVE", "confidence": 60, "findings": []})

    configure(monkeypatch, diff_text, responder=responder)
    provision(client)

    body = start(client)

    assert body["status"] == "draft"
    assert body["thread_count"] == 0
    assert body["suggested_verdict"] == "APPROVE"
    assert body["confidence_percentage"] == 90


def test_an_oversized_single_file_gets_one_part_and_loses_whole_hunks(client, monkeypatch):
    # ~110 000 characters in one file, split into hunks of 100 lines.
    diff_text = build_diff(1, lines=1_200, hunk_lines=100)

    def responder(prompt: str, _index: int) -> str:
        return verdict_payload() if VERDICT_MARKER in prompt else default_findings(prompt)

    calls = configure(monkeypatch, diff_text, responder=responder)
    provision(client)

    body = start(client)

    # One file can only ever be one part, so no verdict pass runs.
    assert len(calls) == 1
    assert body["thread_count"] == 1
    assert any("truncated" in note for note in body["warnings"])
    assert "further hunk(s) of this file omitted" in calls[0]["prompt"]
