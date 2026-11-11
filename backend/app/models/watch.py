"""A watched pull request: when its head moves, a delta review starts by itself.

One row per (account, change request). It carries everything the next review needs — the PR
identity, the foundation and model to reuse — plus the two pieces of state that make a tick
idempotent: `last_seen_commit_id` (the delta base) and `last_review_id` (the parent of the next
linked review).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ReviewTrigger:
    """Why a review row exists. `None` on a review means the operator started it by hand."""

    WATCH = "watch"

    ALL = (WATCH,)


class ReviewWatch(Base):
    __tablename__ = "review_watches"
    __table_args__ = (
        UniqueConstraint("user_id", "pr_url", name="uq_review_watches_user_pr"),
        Index("ix_review_watches_last_checked_at", "last_checked_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pr_url: Mapped[str] = mapped_column(Text, nullable=False)
    vcs: Mapped[str] = mapped_column(
        String(16), nullable=False, default="github", server_default="github"
    )
    repo_full_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Reused for every delta review of this PR.
    skill_foundation: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The delta base: the head this watch has already accounted for. NULL until the first check.
    last_seen_commit_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The review the next delta review continues; also where the dashboard links.
    last_review_id: Mapped[int | None] = mapped_column(
        ForeignKey("code_reviews.id", ondelete="SET NULL"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # First line of the last failure only — never a prompt, a diff, or a credential.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
