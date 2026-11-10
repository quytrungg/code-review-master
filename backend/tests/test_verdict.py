from __future__ import annotations

import json

import pytest

from app.services import llm_service, verdict
from app.services.prompts import build_verdict_prompt
from app.services.verdict import VerdictOutcome, parse_outcome
from tests.fixtures import PR_URL, as_result, provision
from tests.test_review_pipeline import FINDINGS, configure


def test_verdict_is_normalised_and_confidence_clamped():
    outcome = parse_outcome({"verdict": "request-changes", "confidence": "140%", "rationale": "x"})
    assert outcome == VerdictOutcome(verdict="REQUEST_CHANGES", confidence=100, rationale="x")

    assert parse_outcome({"verdict": "merge it"}) is None
    assert parse_outcome(["APPROVE"]) is None
    assert parse_outcome({"confidence": 90}) is None


def test_rationale_is_collapsed_to_one_line_and_capped():
    outcome = parse_outcome(
        {"verdict": "COMMENT", "confidence": 40, "rationale": "  spaced\n\nout   reason  " + "x" * 400}
    )
    assert outcome.rationale.startswith("spaced out reason")
    assert "\n" not in outcome.rationale
    assert len(outcome.rationale) <= verdict.MAX_RATIONALE_CHARS


def test_prompt_lists_threads_and_contract():
    class Message:
        def __init__(self, role, content):
            self.role = role
            self.content = content

    class Thread:
        file_path = "app/a.rb"
        line_number = 12
        dropped = True
        messages = [
            Message("assistant", "**High** — guard the nil"),
            Message("user", "That guard already exists upstream"),
            Message("assistant", "Agreed, withdrawing this one"),
        ]

    prompt = build_verdict_prompt([Thread()])
    assert "## #1 `app/a.rb:12` (withdrawn during discussion)" in prompt
    assert "Original finding: **High** — guard the nil" in prompt
    assert "Latest conclusion: Agreed, withdrawing this one" in prompt
    assert "Reviewer's last message: That guard already exists upstream" in prompt
    assert '"verdict"' in prompt


def _seed(client, monkeypatch):
    from tests.conftest import start_review

    configure(monkeypatch, json.dumps({**{"verdict": "REQUEST_CHANGES", "confidence": 60}, "findings": FINDINGS}))
    provision(client)
    return start_review(client, PR_URL, "ollama-local:llama3")


def test_discussion_refreshes_the_opinion(client, monkeypatch):
    review = _seed(client, monkeypatch)
    thread_id = review["threads"][0]["id"]

    async def generate(credentials, model, system_prompt, user_prompt, json_mode=False, **kwargs):
        if "Review state" in user_prompt:
            return json.dumps(
                {"verdict": "APPROVE", "confidence": 88, "rationale": "Both findings were resolved."}
            )
        return "Agreed — this is fine as written."

    monkeypatch.setattr(llm_service, "generate", as_result(generate))

    response = client.post(
        f"/api/reviews/{review['id']}/discuss",
        json={"threads": [{"thread_id": thread_id, "message": "We already guard this."}]},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["opinion_refreshed"] is True
    assert body["warnings"] == []
    assert body["review"]["suggested_verdict"] == "APPROVE"
    assert body["review"]["confidence_percentage"] == 88
    assert body["review"]["suggested_verdict_note"] == "Both findings were resolved."

    # Persisted, not just echoed.
    stored = client.get(f"/api/reviews/{review['id']}").json()
    assert stored["suggested_verdict"] == "APPROVE"
    assert stored["suggested_verdict_note"] == "Both findings were resolved."


def test_failed_verdict_pass_keeps_the_previous_opinion(client, monkeypatch):
    review = _seed(client, monkeypatch)
    thread_id = review["threads"][0]["id"]

    async def generate(credentials, model, system_prompt, user_prompt, json_mode=False, **kwargs):
        if "Review state" in user_prompt:
            raise llm_service.LLMError("provider went away")
        return "Noted."

    monkeypatch.setattr(llm_service, "generate", as_result(generate))

    response = client.post(
        f"/api/reviews/{review['id']}/discuss",
        json={"threads": [{"thread_id": thread_id, "message": "Still a problem?"}]},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["opinion_refreshed"] is False
    assert body["warnings"]
    assert body["review"]["suggested_verdict"] == "REQUEST_CHANGES"
    assert body["review"]["confidence_percentage"] == 60
    # The reply itself was still stored.
    assert body["review"]["threads"][0]["messages"][-1]["content"] == "Noted."


def test_unparsable_verdict_answer_is_not_applied(client, monkeypatch):
    review = _seed(client, monkeypatch)
    thread_id = review["threads"][0]["id"]

    async def generate(credentials, model, system_prompt, user_prompt, json_mode=False, **kwargs):
        if "Review state" in user_prompt:
            return "I think it looks good!"
        return "Sure."

    monkeypatch.setattr(llm_service, "generate", as_result(generate))

    body = client.post(
        f"/api/reviews/{review['id']}/discuss",
        json={"threads": [{"thread_id": thread_id, "message": "ok?"}]},
    ).json()

    assert body["opinion_refreshed"] is False
    assert body["review"]["suggested_verdict"] == "REQUEST_CHANGES"


@pytest.mark.parametrize("document", [{"verdict": "APPROVE"}, {"verdict": "COMMENT", "confidence": None}])
def test_minimal_documents_are_accepted(document):
    outcome = parse_outcome(document)
    assert outcome is not None
    assert outcome.confidence is None or isinstance(outcome.confidence, int)
