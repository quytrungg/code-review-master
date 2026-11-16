"""Verdict push-back: the reviewer's argument, the model's answer, and what is stored.

The model is stubbed at `llm_service.generate` — the same boundary the rest of the suite uses — so
these tests pin the contract (parse, adopt-or-hold, guards) rather than the wire format.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select, text

from app.db.session import SessionLocal
from app.models.llm_call import LLMCall, LLMPurpose
from app.models.review import CodeReview, MessageRole, ReviewStatus, ReviewThread, ThreadMessage
from app.models.verdict_pushback import VerdictPushback
from app.models.watch import ReviewTrigger
from app.services import llm_service, prompts, verdict
from tests.conftest import TEST_EMAIL
from tests.fixtures import PR_URL, create_llm_key, llm_result

AGREES = {
    "agrees": True,
    "verdict": "COMMENT",
    "confidence": 55,
    "response": "The migration is additive and the flag is off, so I withdraw the block.",
}
DISAGREES = {
    "agrees": False,
    "verdict": "REQUEST_CHANGES",
    "confidence": 80,
    "response": "Nothing rolls back the backfill; a missing down path still blocks the merge.",
}


def _user_id() -> int:
    with SessionLocal() as db:
        return db.execute(
            text("SELECT id FROM users WHERE email = :email"), {"email": TEST_EMAIL}
        ).scalar_one()


def _review(
    *,
    status: str = ReviewStatus.IN_DISCUSSION,
    suggestion: str | None = "REQUEST_CHANGES",
    confidence: int | None = 78,
    note: str | None = "The backfill has no down path.",
    trigger: str | None = None,
    with_thread: bool = True,
    model: str = "ollama-local:llama3",
) -> int:
    with SessionLocal() as db:
        review = CodeReview(
            user_id=_user_id(),
            pr_url=PR_URL,
            vcs="github",
            pr_title="Add the flag",
            pr_number=123,
            repo_full_name="octo/example",
            commit_id="abc123sha",
            model_used=model,
            skill_foundation="code-review",
            status=status,
            suggested_verdict=suggestion,
            confidence_percentage=confidence,
            suggested_verdict_note=note,
            trigger=trigger,
        )
        db.add(review)
        db.commit()
        db.refresh(review)
        review_id = review.id
        if with_thread:
            thread = ReviewThread(
                review_id=review_id,
                file_path="app/payroll/apply.rb",
                line_number=35,
                diff_hunk="@@ -30,6 +30,9 @@",
                origin="AI_GENERATED",
                thread_status="active",
            )
            db.add(thread)
            db.commit()
            db.refresh(thread)
            db.add(
                ThreadMessage(
                    thread_id=thread.id,
                    role=MessageRole.ASSISTANT,
                    content="`validate` only rejects a blank payroll info.",
                )
            )
            db.commit()
        return review_id


def _stub_generate(monkeypatch, payload: dict | None = None, *, error: Exception | None = None):
    """Replace the one call the push-back makes, and capture the purpose it was made under."""
    calls: list[dict] = []

    async def fake_generate(*args, **kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        body = json.dumps(payload)
        return llm_result(body)

    monkeypatch.setattr(llm_service, "generate", fake_generate)
    return calls


def _pushbacks(review_id: int) -> list[VerdictPushback]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(VerdictPushback)
                .where(VerdictPushback.review_id == review_id)
                .order_by(VerdictPushback.id)
            )
        )


def _stored(review_id: int) -> CodeReview:
    with SessionLocal() as db:
        return db.get(CodeReview, review_id)


# --- the loop ----------------------------------------------------------------------------------


def test_an_agreeing_answer_rewrites_the_opinion_and_records_the_exchange(client, monkeypatch):
    create_llm_key(client, provider="ollama_local")
    review_id = _review()
    calls = _stub_generate(monkeypatch, AGREES)

    response = client.post(
        f"/api/reviews/{review_id}/verdict/pushback",
        json={"argument": "The migration is additive and the flag is off in production."},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    pushback = body["pushback"]
    assert pushback["agrees"] is True
    assert (pushback["previous_verdict"], pushback["previous_confidence"]) == ("REQUEST_CHANGES", 78)
    assert (pushback["verdict"], pushback["confidence"]) == ("COMMENT", 55)
    assert pushback["response"] == AGREES["response"]
    assert pushback["created_at"]

    # The advisory opinion moved with it, so the action bar's AI block updates on refresh.
    assert body["review"]["suggested_verdict"] == "COMMENT"
    assert body["review"]["confidence_percentage"] == 55
    assert body["review"]["suggested_verdict_note"] == AGREES["response"]
    assert _stored(review_id).suggested_verdict == "COMMENT"

    # One call, made under its own purpose so contested opinions are visible in the spend split.
    assert len(calls) == 1
    assert calls[0]["purpose"] == LLMPurpose.PUSHBACK
    assert calls[0]["json_mode"] is True


def test_a_disagreeing_answer_keeps_the_opinion_and_records_why(client, monkeypatch):
    create_llm_key(client, provider="ollama_local")
    review_id = _review()
    _stub_generate(monkeypatch, DISAGREES)

    body = client.post(
        f"/api/reviews/{review_id}/verdict/pushback",
        json={"argument": "It is fine, honestly."},
    ).json()

    assert body["pushback"]["agrees"] is False
    assert body["review"]["suggested_verdict"] == "REQUEST_CHANGES"
    assert body["review"]["confidence_percentage"] == 78
    assert body["review"]["suggested_verdict_note"] == "The backfill has no down path."

    rows = _pushbacks(review_id)
    assert len(rows) == 1
    assert rows[0].agrees is False
    assert rows[0].response == DISAGREES["response"]


def test_the_history_is_newest_first(client, monkeypatch):
    create_llm_key(client, provider="ollama_local")
    review_id = _review()
    _stub_generate(monkeypatch, DISAGREES)

    client.post(f"/api/reviews/{review_id}/verdict/pushback", json={"argument": "First objection."})
    client.post(f"/api/reviews/{review_id}/verdict/pushback", json={"argument": "Second objection."})

    history = client.get(f"/api/reviews/{review_id}/verdict/pushbacks").json()

    assert [row["argument"] for row in history] == ["Second objection.", "First objection."]


def test_the_prompt_carries_the_opinion_the_state_and_the_argument():
    review_id = _review()
    with SessionLocal() as db:
        review = db.get(CodeReview, review_id)
        prompt = prompts.build_verdict_pushback_prompt(
            review, list(review.threads), "The backfill is safe."
        )

    assert "REQUEST_CHANGES" in prompt
    assert "78%" in prompt
    assert "The backfill has no down path." in prompt
    assert "`validate` only rejects a blank payroll info." in prompt
    assert "The backfill is safe." in prompt
    assert '"agrees": true | false' in prompt
    # The opinion pass' own contract must not leak in — the answer shape is different.
    assert '"rationale"' not in prompt


# --- guards ------------------------------------------------------------------------------------


@pytest.mark.parametrize("argument", ["", "   ", "\n\t "])
def test_a_blank_argument_is_rejected(client, argument):
    review_id = _review()

    response = client.post(
        f"/api/reviews/{review_id}/verdict/pushback", json={"argument": argument}
    )

    assert response.status_code == 422
    assert _pushbacks(review_id) == []


def test_an_over_long_argument_is_rejected(client):
    review_id = _review()

    response = client.post(
        f"/api/reviews/{review_id}/verdict/pushback", json={"argument": "x" * 2001}
    )

    assert response.status_code == 422
    assert _pushbacks(review_id) == []


def test_a_review_without_an_opinion_cannot_be_pushed_back(client):
    review_id = _review(suggestion=None, confidence=None, note=None)

    response = client.post(
        f"/api/reviews/{review_id}/verdict/pushback", json={"argument": "Disagree."}
    )

    assert response.status_code == 409
    assert "no AI opinion" in response.json()["detail"]


def test_a_running_review_cannot_be_pushed_back(client):
    review_id = _review(status=ReviewStatus.RUNNING)

    response = client.post(
        f"/api/reviews/{review_id}/verdict/pushback", json={"argument": "Disagree."}
    )

    assert response.status_code == 409
    assert "still running" in response.json()["detail"]


def test_a_comparison_review_is_read_only(client):
    review_id = _review(trigger=ReviewTrigger.COMPARISON)

    response = client.post(
        f"/api/reviews/{review_id}/verdict/pushback", json={"argument": "Disagree."}
    )

    assert response.status_code == 409
    assert "read-only" in response.json()["detail"]


def test_another_accounts_review_is_a_404(client, second_client, monkeypatch):
    create_llm_key(client, provider="ollama_local")
    review_id = _review()
    _stub_generate(monkeypatch, AGREES)

    response = second_client.post(
        f"/api/reviews/{review_id}/verdict/pushback", json={"argument": "Disagree."}
    )

    assert response.status_code == 404
    assert _pushbacks(review_id) == []


# --- failures ----------------------------------------------------------------------------------


def test_a_provider_failure_writes_nothing_and_keeps_the_opinion(client, monkeypatch):
    create_llm_key(client, provider="ollama_local")
    review_id = _review()
    _stub_generate(monkeypatch, error=llm_service.LLMError("OpenAI returned HTTP 502"))

    response = client.post(
        f"/api/reviews/{review_id}/verdict/pushback", json={"argument": "Disagree."}
    )

    assert response.status_code == 502
    assert "did not answer" in response.json()["detail"]
    assert _pushbacks(review_id) == []
    assert _stored(review_id).suggested_verdict == "REQUEST_CHANGES"


def test_an_unreadable_answer_writes_nothing(client, monkeypatch):
    create_llm_key(client, provider="ollama_local")
    review_id = _review()

    async def fake_generate(*args, **kwargs):
        return llm_result("I think you might be right, but I cannot say.")

    monkeypatch.setattr(llm_service, "generate", fake_generate)

    response = client.post(
        f"/api/reviews/{review_id}/verdict/pushback", json={"argument": "Disagree."}
    )

    assert response.status_code == 502
    # The adapter itself rejects prose, so the failure never reaches the shape check.
    assert "did not answer" in response.json()["detail"]
    assert _pushbacks(review_id) == []
    assert _stored(review_id).suggested_verdict == "REQUEST_CHANGES"


def test_a_wrong_shaped_answer_writes_nothing(client, monkeypatch):
    """Valid JSON that answers a different question is refused too: the opinion must not move."""
    create_llm_key(client, provider="ollama_local")
    review_id = _review()
    _stub_generate(monkeypatch, {"verdict": "COMMENT", "rationale": "no agrees field"})

    response = client.post(
        f"/api/reviews/{review_id}/verdict/pushback", json={"argument": "Disagree."}
    )

    assert response.status_code == 502
    assert "could not be read" in response.json()["detail"]
    assert _pushbacks(review_id) == []
    assert _stored(review_id).suggested_verdict == "REQUEST_CHANGES"


def test_a_missing_key_is_a_422_not_a_502(client, monkeypatch):
    """No key means no request was sent: that is the operator's to fix, not the provider's fault."""
    review_id = _review(model="claude:claude-sonnet-4-5-20250929")

    response = client.post(
        f"/api/reviews/{review_id}/verdict/pushback", json={"argument": "Disagree."}
    )

    assert response.status_code == 422
    assert "No Claude key configured" in response.json()["detail"]


# --- parsing -----------------------------------------------------------------------------------


def test_parse_pushback_requires_a_boolean_and_a_response():
    assert verdict.parse_pushback({"agrees": "yes", "verdict": "COMMENT", "response": "ok"}) is None
    assert verdict.parse_pushback({"agrees": True, "verdict": "COMMENT"}) is None
    assert verdict.parse_pushback({"agrees": True, "verdict": "MAYBE", "response": "ok"}) is None
    assert verdict.parse_pushback(["not", "a", "document"]) is None


def test_parse_pushback_normalises_the_answer():
    outcome = verdict.parse_pushback(
        {"agrees": True, "verdict": "request changes", "confidence": "61%",
         "response": "  Two   sentences.\nSecond line.  "}
    )

    assert outcome is not None
    assert outcome.verdict == "REQUEST_CHANGES"
    assert outcome.confidence == 61
    assert outcome.response == "Two sentences. Second line."


def test_a_pushback_call_is_recorded_in_the_ledger(client, monkeypatch):
    """With the real adapter stubbed one layer lower, the ledger row must still appear."""
    import httpx

    create_llm_key(client, provider="ollama_local")
    review_id = _review()

    def handler(request):
        return httpx.Response(
            200,
            json={
                "model": "llama3",
                "message": {"role": "assistant", "content": json.dumps(AGREES)},
                "done": True,
                "prompt_eval_count": 900,
                "eval_count": 60,
            },
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    response = client.post(
        f"/api/reviews/{review_id}/verdict/pushback", json={"argument": "The flag is off."}
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as db:
        rows = db.execute(
            select(LLMCall.purpose, LLMCall.provider)
            .where(LLMCall.review_id == review_id)
            .order_by(LLMCall.id)
        ).all()
        assert (LLMPurpose.PUSHBACK, "ollama-local") in rows
        ledger_calls = db.execute(
            select(func.count())
            .select_from(LLMCall)
            .where(LLMCall.review_id == review_id, LLMCall.purpose == LLMPurpose.PUSHBACK)
        ).scalar_one()
        assert ledger_calls == 1
