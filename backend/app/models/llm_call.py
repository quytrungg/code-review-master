"""The LLM call ledger.

One row per provider call: which review and thread it served, what it was for, how many tokens it
reported, what that is estimated to cost, how long it took and whether it worked.

**Privacy (`rules/privacy.md`):** prompts, system prompts, diffs, completions and reviewer messages
are never written here. Only counts, enumerations, a class name and an internal id. The ledger is
deliberately useless for reading back what was reviewed.

Ownership is reached through `review_id → code_reviews.user_id`; there is no `user_id` column, so
the two can never disagree. A row whose `review_id` is NULL (a call outside any review) is not
attributable to an account and analytics ignores it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class LLMPurpose:
    """Why the call was made. One value per call site, so spend can be split by activity."""

    INGEST = "ingest"
    DISCUSS = "discuss"
    VERDICT = "verdict"
    SUMMARISE = "summarise"
    # The inbox's one-shot prose polish for a quick-review draft.
    POLISH = "polish"
    # The skill-evolution meta-analysis (phase 34): one call over the guidelines and the
    # recent review history. It belongs to no single review, so it carries no review id.
    EVOLVE = "evolve"
    # The push-back lesson draft (phase 36): one call over a rejected finding, beta-gated.
    LESSON = "lesson"

    ALL = (INGEST, DISCUSS, VERDICT, SUMMARISE, POLISH, EVOLVE, LESSON)


class LLMCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        # Per-review usage line: "4 calls · 61k tokens" in the review header.
        Index("ix_llm_calls_review_id_created", "review_id", "created_at"),
        # The analytics window, grouped the way the page groups it.
        Index("ix_llm_calls_analytics", "created_at", "provider", "model", "purpose"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # A review's own calls disappear with it; a call survives its thread being deleted.
    review_id: Mapped[int | None] = mapped_column(
        ForeignKey("code_reviews.id", ondelete="CASCADE"), nullable=True
    )
    thread_id: Mapped[int | None] = mapped_column(
        ForeignKey("review_threads.id", ondelete="SET NULL"), nullable=True
    )
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    # Model-id prefix (claude, openai, ollama-cloud, ollama-local) and the bare model name.
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    # NULL, never 0, when the provider or model does not report a count.
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # NULL means "no price for this model", which the UI shows as unknown rather than free.
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    ok: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # The exception's class name (RateLimitError, ConnectError), never its message.
    error_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
