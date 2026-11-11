"""Aggregation, quality ratios, budget utilisation and account isolation for `/api/analytics`.

The fixture is fixed data, not a model run: four calls with known latencies and counts, and three
AI findings whose latest rounds end `published`, `drafting` (with a reply) and `resolved_no_reply`.
Every expected number below can be worked out by hand from `seed_calls`.
"""

from __future__ import annotations

from sqlalchemy import select, text

from app.db.session import SessionLocal
from app.models.llm_call import LLMCall
from app.models.review import (
    CodeReview,
    MessageRole,
    ReviewThread,
    ReviewStatus,
    RoundStatus,
    ThreadMessage,
    ThreadOrigin,
    ThreadRound,
)
from tests.conftest import TEST_EMAIL

CLAUDE = "claude:claude-sonnet-4-5-20250929"
OLLAMA = "ollama-local:llama3"


def seed_quality() -> dict:
    """Two reviews and three AI findings: one accepted, two pushed back."""
    with SessionLocal() as db:
        owner = db.execute(
            text("SELECT id FROM users WHERE email = :email"), {"email": TEST_EMAIL}
        ).scalar_one()

        claude_review = CodeReview(
            user_id=owner,
            pr_url="https://github.com/octo/example/pull/201",
            vcs="github",
            pr_title="Accepted and discussed",
            pr_number=201,
            repo_full_name="octo/example",
            model_used=CLAUDE,
            status=ReviewStatus.IN_DISCUSSION,
        )
        ollama_review = CodeReview(
            user_id=owner,
            pr_url="https://github.com/octo/example/pull/202",
            vcs="github",
            pr_title="Discarded",
            pr_number=202,
            repo_full_name="octo/example",
            model_used=OLLAMA,
            status=ReviewStatus.DRAFT,
        )
        db.add_all([claude_review, ollama_review])
        db.commit()

        accepted = ReviewThread(
            review_id=claude_review.id,
            file_path="src/a.py",
            line_number=10,
            diff_hunk="+x",
            origin=ThreadOrigin.AI_GENERATED,
        )
        discussed = ReviewThread(
            review_id=claude_review.id,
            file_path="src/b.py",
            line_number=20,
            diff_hunk="+y",
            origin=ThreadOrigin.AI_GENERATED,
        )
        imported = ReviewThread(
            review_id=claude_review.id,
            file_path="src/c.py",
            line_number=30,
            diff_hunk="+z",
            origin=ThreadOrigin.GITHUB_EXISTING,
        )
        discarded = ReviewThread(
            review_id=ollama_review.id,
            file_path="src/d.py",
            line_number=40,
            diff_hunk="+w",
            origin=ThreadOrigin.AI_GENERATED,
            dropped=True,
        )
        db.add_all([accepted, discussed, imported, discarded])
        db.commit()

        db.add_all(
            [
                ThreadRound(
                    thread_id=accepted.id, round_number=1, status=RoundStatus.PUBLISHED
                ),
                ThreadRound(
                    thread_id=discussed.id, round_number=1, status=RoundStatus.DRAFTING
                ),
                ThreadRound(
                    thread_id=imported.id, round_number=1, status=RoundStatus.PUBLISHED
                ),
                ThreadRound(
                    thread_id=discarded.id,
                    round_number=1,
                    status=RoundStatus.RESOLVED_NO_REPLY,
                ),
                # The reviewer engaged on the second finding: that is what push-back counts.
                ThreadMessage(
                    thread_id=discussed.id,
                    role=MessageRole.USER,
                    content="We already guard this upstream.",
                    round_number=1,
                ),
            ]
        )
        db.commit()

        return {
            "claude_review": claude_review.id,
            "ollama_review": ollama_review.id,
            "accepted_thread": accepted.id,
        }


def seed_calls(claude_review_id: int, ollama_review_id: int) -> None:
    """Four calls: three priced Claude calls and one failed, unpriced Ollama call."""
    with SessionLocal() as db:
        db.add_all(
            [
                LLMCall(
                    review_id=claude_review_id,
                    purpose="ingest",
                    provider="claude",
                    model="claude-sonnet-4-5-20250929",
                    prompt_tokens=1000,
                    completion_tokens=500,
                    total_tokens=1500,
                    estimated_cost_usd=0.0105,
                    latency_ms=100,
                ),
                LLMCall(
                    review_id=claude_review_id,
                    purpose="discuss",
                    provider="claude",
                    model="claude-sonnet-4-5-20250929",
                    prompt_tokens=500,
                    completion_tokens=250,
                    total_tokens=750,
                    estimated_cost_usd=0.00525,
                    latency_ms=200,
                ),
                LLMCall(
                    review_id=claude_review_id,
                    purpose="verdict",
                    provider="claude",
                    model="claude-sonnet-4-5-20250929",
                    prompt_tokens=2000,
                    completion_tokens=100,
                    total_tokens=2100,
                    estimated_cost_usd=0.0075,
                    latency_ms=300,
                ),
                LLMCall(
                    review_id=ollama_review_id,
                    purpose="ingest",
                    provider="ollama-local",
                    model="llama3",
                    prompt_tokens=None,
                    completion_tokens=None,
                    total_tokens=None,
                    estimated_cost_usd=None,
                    latency_ms=400,
                    ok=False,
                    error_class="ConnectError",
                ),
            ]
        )
        db.commit()


def seed_all() -> dict:
    ids = seed_quality()
    seed_calls(ids["claude_review"], ids["ollama_review"])
    return ids


def test_analytics_requires_a_session(anon_client):
    response = anon_client.get("/api/analytics")
    assert response.status_code == 401


def test_totals_volume_and_cost(client):
    seed_all()
    body = client.get("/api/analytics?days=30").json()

    totals = body["totals"]
    assert totals["calls"] == 4
    assert totals["failed_calls"] == 1
    assert totals["priced_calls"] == 3
    assert totals["prompt_tokens"] == 3500
    assert totals["completion_tokens"] == 850
    assert totals["total_tokens"] == 4350
    assert totals["estimated_cost_usd"] == 0.02325
    assert body["window_days"] == 30

    purposes = {row["purpose"]: row for row in body["by_purpose"]}
    assert list(purposes) == ["ingest", "discuss", "verdict", "summarise", "polish"]
    assert purposes["ingest"]["calls"] == 2
    assert purposes["ingest"]["total_tokens"] == 1500
    assert purposes["discuss"]["calls"] == 1
    assert purposes["summarise"]["calls"] == 0
    assert purposes["summarise"]["estimated_cost_usd"] is None


def test_latency_percentiles_and_model_rows(client):
    seed_all()
    body = client.get("/api/analytics").json()

    # Latencies 100, 200, 300, 400 → nearest rank: median is the 2nd, p95 the 4th.
    assert body["latency"] == {"median_ms": 200, "p95_ms": 400, "avg_ms": 250}

    models = {row["model"]: row for row in body["by_model"]}
    claude = models[CLAUDE]
    assert claude["provider"] == "claude"
    assert claude["calls"] == 3
    assert claude["prompt_tokens"] == 3500
    assert claude["completion_tokens"] == 850
    assert claude["estimated_cost_usd"] == 0.02325
    assert claude["avg_latency_ms"] == 200
    # Two AI findings on this review: one published, one discussed → 50% / 50%.
    assert (claude["findings"], claude["accepted"], claude["acceptance_rate"]) == (2, 1, 50.0)
    assert (claude["pushed_back"], claude["pushback_rate"]) == (1, 50.0)

    ollama = models[OLLAMA]
    assert ollama["calls"] == 1
    assert ollama["estimated_cost_usd"] is None  # nothing on this model was priced
    assert (ollama["findings"], ollama["accepted"], ollama["acceptance_rate"]) == (1, 0, 0.0)
    assert ollama["pushback_rate"] == 100.0  # resolved_no_reply is a push-back

    providers = {row["provider"]: row for row in body["by_provider"]}
    assert providers["claude"]["calls"] == 3
    assert providers["ollama-local"]["calls"] == 1
    assert providers["ollama-local"]["estimated_cost_usd"] is None


def test_quality_ratios_exclude_imported_threads(client):
    seed_all()
    body = client.get("/api/analytics").json()

    quality = body["quality"]
    # Three AI findings (the imported GitHub thread is not the model's work).
    assert quality["findings"] == 3
    assert quality["accepted"] == 1
    assert quality["acceptance_rate"] == 33.3
    assert quality["pushed_back"] == 2
    assert quality["pushback_rate"] == 66.7


def test_window_excludes_older_calls(client):
    seed_all()
    with SessionLocal() as db:
        row = db.scalars(select(LLMCall).where(LLMCall.purpose == "verdict")).one()
        row.created_at = row.created_at.replace(year=row.created_at.year - 1)
        db.commit()

    body = client.get("/api/analytics?days=30").json()
    assert body["totals"]["calls"] == 3
    assert body["totals"]["estimated_cost_usd"] == 0.01575


def test_budget_utilises_the_current_month_and_warns(client):
    seed_all()

    saved = client.put(
        "/api/settings", json={"monthly_token_budget": 5000, "monthly_dollar_budget": 1.0}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["monthly_token_budget"] == 5000

    budget = client.get("/api/analytics").json()["budget"]
    assert budget["token_budget"] == 5000
    assert budget["tokens_used"] == 4350
    assert budget["token_pct"] == 87.0
    assert budget["dollar_budget"] == 1.0
    assert budget["dollars_used"] == 0.02325
    assert budget["dollar_pct"] == 2.3
    assert budget["level"] == "warn"  # 87% is over the 80% warning line

    # A tighter cap is simply over 100%; nothing is blocked, the level just says so.
    client.put("/api/settings", json={"monthly_token_budget": 1000})
    budget = client.get("/api/analytics").json()["budget"]
    assert budget["level"] == "over"
    assert budget["token_pct"] == 435.0

    # Clearing the cap returns to "ok" and no percentage.
    client.put("/api/settings", json={"monthly_token_budget": None})
    budget = client.get("/api/analytics").json()["budget"]
    assert budget["token_budget"] is None
    assert budget["token_pct"] is None
    assert budget["level"] == "ok"


def test_another_account_sees_none_of_it(client, second_client):
    seed_all()
    mine = client.get("/api/analytics").json()
    assert mine["totals"]["calls"] == 4

    other = second_client.get("/api/analytics").json()
    assert other["totals"]["calls"] == 0
    assert other["totals"]["total_tokens"] == 0
    assert other["totals"]["estimated_cost_usd"] is None
    assert other["quality"]["findings"] == 0
    assert other["by_model"] == []
    assert other["latency"] == {"median_ms": None, "p95_ms": None, "avg_ms": None}


def test_review_detail_carries_its_own_usage(client):
    ids = seed_all()
    detail = client.get(f"/api/reviews/{ids['claude_review']}").json()
    assert detail["usage"] == {
        "calls": 3,
        "prompt_tokens": 3500,
        "completion_tokens": 850,
        "total_tokens": 4350,
        "estimated_cost_usd": 0.02325,
        "latency_ms": 600,
    }

    other = client.get(f"/api/reviews/{ids['ollama_review']}").json()
    assert other["usage"]["calls"] == 1
    assert other["usage"]["total_tokens"] == 0
    assert other["usage"]["estimated_cost_usd"] is None


def test_days_outside_the_range_is_rejected(client):
    assert client.get("/api/analytics?days=0").status_code == 422
    assert client.get("/api/analytics?days=366").status_code == 422


def test_settings_round_trip_keeps_the_caps(client):
    client.put("/api/settings", json={"monthly_token_budget": 123456, "monthly_dollar_budget": 9.5})
    body = client.get("/api/settings").json()
    assert body["monthly_token_budget"] == 123456
    assert body["monthly_dollar_budget"] == 9.5

    # An absent field is untouched (the key ids still behave the same way).
    client.put("/api/settings", json={"monthly_dollar_budget": 12.0})
    body = client.get("/api/settings").json()
    assert body["monthly_token_budget"] == 123456
    assert body["monthly_dollar_budget"] == 12.0
