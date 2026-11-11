"""Skill evolution: history aggregation, proposal validation and the filesystem writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.review import (
    CodeReview,
    MessageRole,
    ReviewThread,
    RoundStatus,
    ThreadMessage,
    ThreadOrigin,
    ThreadRound,
)
from app.services import llm_service, skill_analyzer_service
from tests.fixtures import as_result, create_llm_key

FOUNDATION = "code-review"


def _skills_dir() -> Path:
    return get_settings().resolved_skills_dir


def _foundations_dir() -> Path:
    return get_settings().resolved_foundations_dir


def _user_id() -> int:
    from app.models.user import User

    with SessionLocal() as db:
        user = db.query(User).first()
        assert user is not None
        return user.id


def _seed_thread(
    *,
    file_path: str = "src/services/auth.py",
    line_number: int = 12,
    ai_text: str = "**High** — the JWT check is missing.",
    reviewer_text: str | None = None,
    rounds: list[tuple[int, str]] | None = None,
    dropped: bool = False,
    published_summary: str | None = None,
    days_ago: int = 1,
) -> tuple[int, int]:
    """Create one review with one AI thread. Returns (review id, thread id)."""
    from datetime import timedelta

    from app.db.base import utcnow

    with SessionLocal() as db:
        review = CodeReview(
            user_id=_user_id(),
            pr_url="https://github.com/octo/example/pull/900",
            vcs="github",
            pr_title="Seed review",
            pr_number=900,
            repo_full_name="octo/example",
            model_used="ollama-local:llama3",
            skill_foundation=FOUNDATION,
            status="applied",
            created_at=utcnow() - timedelta(days=days_ago),
        )
        db.add(review)
        db.flush()

        thread = ReviewThread(
            review_id=review.id,
            file_path=file_path,
            line_number=line_number,
            diff_hunk="@@ -10,3 +10,4 @@",
            origin=ThreadOrigin.AI_GENERATED,
            current_round=max([number for number, _ in (rounds or [(1, RoundStatus.PUBLISHED)])]),
            dropped=dropped,
            created_at=review.created_at,
        )
        thread.messages.append(
            ThreadMessage(role=MessageRole.ASSISTANT, content=ai_text, round_number=1)
        )
        if reviewer_text:
            thread.messages.append(
                ThreadMessage(role=MessageRole.USER, content=reviewer_text, round_number=1)
            )
        for number, status in rounds or [(1, RoundStatus.PUBLISHED)]:
            thread.rounds.append(
                ThreadRound(
                    round_number=number,
                    status=status,
                    final_summary=published_summary if number == 1 else None,
                )
            )
        db.add(thread)
        db.commit()
        return review.id, thread.id


def _stub_model(monkeypatch, payload: dict) -> list[dict]:
    """Replace the model call with a canned answer; returns the captured prompts."""
    captured: list[dict] = []

    async def fake(credentials, model, system_prompt, user_prompt, **kwargs):
        captured.append(
            {
                "system": system_prompt,
                "user": user_prompt,
                "model": model.id,
                "purpose": kwargs.get("purpose"),
            }
        )
        return json.dumps(payload)

    monkeypatch.setattr(llm_service, "generate", as_result(fake))
    return captured


def _provision(client) -> None:
    create_llm_key(client, provider="ollama_local", default_model="llama3")
    key = client.get("/api/keys/llm").json()[0]
    client.put("/api/settings", json={"llm_key_id": key["id"]})


# --------------------------------------------------------------------------- aggregation


def test_aggregation_keeps_the_friction_and_drops_the_clean_thread(client, monkeypatch):
    """A pushed-back thread is high-signal; an accepted, unchallenged one teaches nothing."""
    _seed_thread(
        file_path="src/services/auth.py",
        ai_text="**High** — the JWT check is missing.",
        reviewer_text="staging mock does not sign keys",
        rounds=[(1, RoundStatus.RESOLVED_NO_REPLY)],
        dropped=True,
    )
    _seed_thread(
        file_path="src/services/clean.py",
        ai_text="**Low** — rename this variable.",
        rounds=[(1, RoundStatus.PUBLISHED)],
    )

    from app.services import skills_service

    files = skills_service.read_foundation_files(FOUNDATION)
    digest = skill_analyzer_service.aggregate_history(
        SessionLocal(), _user_id(), FOUNDATION, 30
    )

    assert digest.review_count == 2
    assert digest.thread_count == 2
    # Only the pushed-back thread survived.
    assert digest.interaction_count == 1
    interaction = digest.interactions[0]
    assert interaction.file_path == "src/services/auth.py"
    assert "staging mock does not sign keys" in digest.text
    assert "src/services/clean.py" not in digest.text
    assert files  # the foundation's rules were readable


def test_aggregation_scores_a_rewritten_published_finding(client, monkeypatch):
    """A finding the reviewer rewrote before publishing is friction too."""
    _seed_thread(
        ai_text="**High** — the query is unbounded.",
        rounds=[(1, RoundStatus.PUBLISHED)],
        published_summary="The query should have a limit.",
    )

    digest = skill_analyzer_service.aggregate_history(
        SessionLocal(), _user_id(), FOUNDATION, 30
    )
    assert digest.interaction_count == 1
    assert "accepted and published" in digest.text


def test_aggregation_respects_the_window(client, monkeypatch):
    _seed_thread(
        reviewer_text="too old",
        rounds=[(1, RoundStatus.RESOLVED_NO_REPLY)],
        days_ago=90,
    )
    digest = skill_analyzer_service.aggregate_history(
        SessionLocal(), _user_id(), FOUNDATION, 30
    )
    assert digest.review_count == 0
    assert digest.interaction_count == 0


# -------------------------------------------------------------------------- the analysis


def test_analysis_returns_a_validated_proposal_with_a_diff(client, monkeypatch):
    _seed_thread(
        reviewer_text="staging mock does not sign keys",
        rounds=[(1, RoundStatus.RESOLVED_NO_REPLY)],
        dropped=True,
    )
    _provision(client)

    captured = _stub_model(
        monkeypatch,
        {
            "analysisSummary": "The AI repeatedly flagged JWT checks in staging fixtures.",
            "fileModifications": [
                {
                    "filePath": "references/ruby.md",
                    "action": "modify",
                    "rationale": "Staging mock keys are not signed.",
                    "evidenceReviewIds": [1],
                    "originalContent": "# Ruby rules\n\nBe careful.",
                    "proposedContent": "# Ruby rules\n\nBe careful.\n\n## Staging mocks\n\nDo not flag unsigned staging keys.",
                }
            ],
        },
    )

    response = client.post(
        f"/api/skills/{FOUNDATION}/analyze-history",
        json={"days": 30, "model": "ollama-local:llama3"},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["analysis_summary"].startswith("The AI repeatedly flagged")
    assert body["history"]["reviews"] == 1
    assert body["history"]["interactions"] == 1

    assert len(body["file_modifications"]) == 1
    proposal = body["file_modifications"][0]
    assert proposal["file_path"] == "references/ruby.md"
    assert proposal["action"] == "modify"
    assert proposal["rationale"] == "Staging mock keys are not signed."
    # The diff is computed against the file on disk, not the copy the model echoed back.
    assert proposal["original_content"] == "# Ruby rules\n\nBe careful."
    assert "## Staging mocks" in proposal["proposed_content"]
    assert "+## Staging mocks" in proposal["unified_diff"]
    assert "-Be careful." in proposal["unified_diff"]

    # The model was asked to play the curator, and the history reached it.
    assert "rule curator" in captured[0]["system"]
    assert "staging mock does not sign keys" in captured[0]["user"]
    assert captured[0]["purpose"] == "evolve"


def test_analysis_drops_an_illegal_path_and_a_no_op(client, monkeypatch):
    _provision(client)
    _stub_model(
        monkeypatch,
        {
            "analysisSummary": "Two proposals, one of them unusable.",
            "fileModifications": [
                {
                    "filePath": "../../../main.py",
                    "action": "modify",
                    "rationale": "escape",
                    "evidenceReviewIds": [],
                    "originalContent": "",
                    "proposedContent": "pwned",
                },
                {
                    "filePath": "references/ruby.md",
                    "action": "modify",
                    "rationale": "no change",
                    "evidenceReviewIds": [],
                    "originalContent": "# Ruby rules\n\nBe careful.",
                    "proposedContent": "# Ruby rules\n\nBe careful.",
                },
            ],
        },
    )

    response = client.post(
        f"/api/skills/{FOUNDATION}/analyze-history",
        json={"days": 30, "model": "ollama-local:llama3"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["file_modifications"] == []
    assert any("../../../main.py" in warning for warning in body["warnings"])
    assert any("changes nothing" in warning for warning in body["warnings"])


def test_analysis_drops_a_modification_of_a_file_that_does_not_exist(client, monkeypatch):
    _provision(client)
    _stub_model(
        monkeypatch,
        {
            "analysisSummary": "Proposed a change to a file that is not there.",
            "fileModifications": [
                {
                    "filePath": "references/ghost.md",
                    "action": "modify",
                    "rationale": "invented",
                    "evidenceReviewIds": [],
                    "originalContent": "",
                    "proposedContent": "new",
                }
            ],
        },
    )
    response = client.post(
        f"/api/skills/{FOUNDATION}/analyze-history",
        json={"days": 30, "model": "ollama-local:llama3"},
    )
    assert response.status_code == 200
    assert response.json()["file_modifications"] == []


def test_analysis_filters_evidence_ids_outside_the_window(client, monkeypatch):
    _seed_thread(
        reviewer_text="wrong here",
        rounds=[(1, RoundStatus.RESOLVED_NO_REPLY)],
    )
    _provision(client)
    _stub_model(
        monkeypatch,
        {
            "analysisSummary": "Cited a review that is not in the window.",
            "fileModifications": [
                {
                    "filePath": "references/ruby.md",
                    "action": "modify",
                    "rationale": "cited id 999999",
                    "evidenceReviewIds": [999999],
                    "originalContent": "",
                    "proposedContent": "# Ruby rules\n\nBe careful.\n\nNew rule.",
                }
            ],
        },
    )
    response = client.post(
        f"/api/skills/{FOUNDATION}/analyze-history",
        json={"days": 30, "model": "ollama-local:llama3"},
    )
    assert response.status_code == 200
    proposal = response.json()["file_modifications"][0]
    assert proposal["evidence_review_ids"] == []


def test_analysis_with_no_proposals_is_a_success(client, monkeypatch):
    _provision(client)
    _stub_model(
        monkeypatch,
        {
            "analysisSummary": "No guideline adjustments needed. Your skill foundation closely "
            "matches your team's review patterns.",
            "fileModifications": [],
        },
    )
    response = client.post(
        f"/api/skills/{FOUNDATION}/analyze-history",
        json={"days": 30, "model": "ollama-local:llama3"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["file_modifications"] == []
    assert "No guideline adjustments needed" in body["analysis_summary"]


def test_analysis_with_an_unknown_model_is_422(client, monkeypatch):
    _provision(client)
    response = client.post(
        f"/api/skills/{FOUNDATION}/analyze-history",
        json={"days": 30, "model": "gpt-4"},
    )
    assert response.status_code == 422
    assert "Unknown model id" in response.json()["detail"]


def test_analysis_with_an_unknown_foundation_is_404(client, monkeypatch):
    _provision(client)
    response = client.post(
        "/api/skills/ghost-foundation/analyze-history",
        json={"days": 30, "model": "ollama-local:llama3"},
    )
    assert response.status_code == 404


# ------------------------------------------------------------------------ filesystem writes


def test_apply_writes_in_place_and_backs_the_foundation_up(client):
    original = (_skills_dir() / "references" / "ruby.md").read_text()
    response = client.post(
        f"/api/skills/{FOUNDATION}/apply",
        json={
            "files": [
                {
                    "file_path": "references/ruby.md",
                    "action": "modify",
                    "content": "# Ruby rules\n\nDo not flag staging mock keys.\n",
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied"] == ["references/ruby.md"]
    assert body["backup_path"]

    # The file changed…
    assert (_skills_dir() / "references" / "ruby.md").read_text() == (
        "# Ruby rules\n\nDo not flag staging mock keys.\n"
    )
    # …and the previous state is recoverable from the backup.
    backup = Path(body["backup_path"])
    assert (backup / "references" / "ruby.md").read_text() == original
    # The untouched sibling is not in the backup's change set but is still copied.
    assert (backup / "SKILL.md").is_file()

    # Restore, so the next test starts from the original text.
    (_skills_dir() / "references" / "ruby.md").write_text(original)


def test_apply_creates_a_new_file(client):
    response = client.post(
        f"/api/skills/{FOUNDATION}/apply",
        json={
            "files": [
                {
                    "file_path": "references/evolution.md",
                    "action": "create",
                    "content": "# Evolution\n\nNew rule.\n",
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    created = _skills_dir() / "references" / "evolution.md"
    assert created.is_file()
    assert created.read_text() == "# Evolution\n\nNew rule.\n"
    created.unlink()


def test_apply_rejects_a_path_outside_the_foundation(client):
    response = client.post(
        f"/api/skills/{FOUNDATION}/apply",
        json={
            "files": [
                {
                    "file_path": "../../../main.py",
                    "action": "modify",
                    "content": "pwned",
                }
            ]
        },
    )
    assert response.status_code == 400
    assert "outside the foundation" in response.json()["detail"]
    assert not (Path("/tmp") / "main.py").exists()


@pytest.mark.parametrize("bad", ["/etc/passwd", "rules.exe", "..\\..\\escape.md"])
def test_apply_rejects_other_unsafe_paths(client, bad):
    response = client.post(
        f"/api/skills/{FOUNDATION}/apply",
        json={"files": [{"file_path": bad, "action": "modify", "content": "x"}]},
    )
    assert response.status_code == 400


def test_apply_of_a_missing_file_is_404(client):
    response = client.post(
        f"/api/skills/{FOUNDATION}/apply",
        json={
            "files": [
                {"file_path": "references/ghost.md", "action": "modify", "content": "x"}
            ]
        },
    )
    assert response.status_code == 404


def test_clone_and_apply_leaves_the_source_untouched(client):
    original = (_skills_dir() / "references" / "ruby.md").read_text()
    response = client.post(
        f"/api/skills/{FOUNDATION}/clone-and-apply",
        json={
            "new_foundation_name": "team-standards-v2",
            "files": [
                {
                    "file_path": "references/ruby.md",
                    "action": "modify",
                    "content": "# Ruby rules\n\nCloned rule.\n",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["foundation"]["id"] == "team-standards-v2"
    assert body["applied"] == ["references/ruby.md"]

    # The source is untouched.
    assert (_skills_dir() / "references" / "ruby.md").read_text() == original
    # The clone has both the base files and the accepted edit.
    clone = _foundations_dir() / "team-standards-v2"
    assert (clone / "SKILL.md").is_file()
    assert (clone / "references" / "ruby.md").read_text() == "# Ruby rules\n\nCloned rule.\n"

    # It is registered immediately: the filesystem is the source of truth.
    listing = client.get("/api/skills").json()
    assert any(item["id"] == "team-standards-v2" for item in listing["foundations"])


def test_clone_with_an_existing_name_is_409(client):
    response = client.post(
        f"/api/skills/{FOUNDATION}/clone-and-apply",
        json={
            "new_foundation_name": "team-standards-v2",
            "files": [{"file_path": "references/ruby.md", "action": "modify", "content": "x"}],
        },
    )
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


@pytest.mark.parametrize("bad", ["Team Standards", "team_standards", "../escape"])
def test_clone_with_an_illegal_name_is_400(client, bad):
    response = client.post(
        f"/api/skills/{FOUNDATION}/clone-and-apply",
        json={
            "new_foundation_name": bad,
            "files": [{"file_path": "references/ruby.md", "action": "modify", "content": "x"}],
        },
    )
    assert response.status_code == 400


def test_clone_rejects_a_path_outside_the_foundation(client):
    response = client.post(
        f"/api/skills/{FOUNDATION}/clone-and-apply",
        json={
            "new_foundation_name": "evil-clone",
            "files": [{"file_path": "../../../main.py", "action": "modify", "content": "x"}],
        },
    )
    assert response.status_code == 400
    assert not (_foundations_dir() / "evil-clone").exists()


def test_the_evolution_endpoints_require_a_session(anon_client):
    response = anon_client.post(
        f"/api/skills/{FOUNDATION}/analyze-history",
        json={"days": 30, "model": "ollama-local:llama3"},
    )
    assert response.status_code == 401
