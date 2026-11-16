"""A standing review policy: "review every PR in this repo that is waiting on me".

One row per instruction. It carries the three things the next review needs (model, foundation,
involvement), the spend guard (`max_active`), and the two pieces of tick state: `last_run_at` for a
fair queue and `last_error` for the first line of a failure. Whether a PR has already been claimed
is tracked on the cached inbox row (`cached_prs.policy_claim_at`), not here, so two ticks cannot
both start a review for one pull request.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class PolicyInvolvement:
    """Which inbox rows a policy applies to. `any` deliberately ignores why the PR concerns you."""

    REVIEWER = "reviewer"
    ASSIGNEE = "assignee"
    AUTHOR = "author"
    ANY = "any"

    ALL = (REVIEWER, ASSIGNEE, AUTHOR, ANY)


class ReviewPolicy(Base):
    __tablename__ = "review_policies"
    __table_args__ = (Index("ix_review_policies_last_run_at", "last_run_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # A glob on `owner/repo`, matched case-insensitively. One explicit repo is the sane default;
    # a wide pattern is a deliberate act, not what the form proposes.
    repo_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    involvement: Mapped[str] = mapped_column(
        String(24), nullable=False, default=PolicyInvolvement.REVIEWER,
        server_default=PolicyInvolvement.REVIEWER,
    )
    model_used: Mapped[str] = mapped_column(Text, nullable=False)
    skill_foundation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Concurrent reviews that this policy started and that are not terminal yet.
    max_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # First line of the last failure only — never a prompt, a diff, or a credential.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
