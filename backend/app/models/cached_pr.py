"""A pull request in the inbox cache: what /inbox shows without calling GitHub.

One row per (account, change request). The cache is rebuilt by `github_inbox_service.sync_inbox`:
rows for PRs that are no longer open and matching are deleted, matches are upserted. Status and
unread state are recomputed from GitHub on every sync — `last_user_action_at` is GitHub truth (the
latest own review or comment), not app truth, so an action taken on GitHub itself moves the clock.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class InboxStatus:
    """Where one inbox item sits in the review turn-taking loop."""

    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REQUEST_CHANGED = "request_changed"
    COMMENTED = "commented"

    ALL = (NEEDS_REVIEW, APPROVED, REQUEST_CHANGED, COMMENTED)
    # Statuses an inbound reply can re-arm back to NEEDS_REVIEW.
    ACTIONABLE = (APPROVED, REQUEST_CHANGED, COMMENTED)


class InboxInvolvement:
    """Why an inbox item concerns this account: review request, assignment, or authorship."""

    REVIEWER = "reviewer"
    ASSIGNEE = "assignee"
    AUTHOR = "author"

    ALL = (REVIEWER, ASSIGNEE, AUTHOR)


class CachedPR(Base):
    __tablename__ = "cached_prs"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "repo_owner", "repo_name", "pr_number", name="uq_cached_prs_user_pr"
        ),
        Index("ix_cached_prs_status", "user_id", "status"),
        Index("ix_cached_prs_github_pr_id", "user_id", "github_pr_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    github_pr_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    repo_owner: Mapped[str] = mapped_column(Text, nullable=False)
    repo_name: Mapped[str] = mapped_column(Text, nullable=False)
    pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    pr_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author_username: Mapped[str] = mapped_column(Text, nullable=False)
    author_avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=InboxStatus.NEEDS_REVIEW,
        server_default=InboxStatus.NEEDS_REVIEW,
    )
    has_unread_replies: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    unread_replies_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Latest own review / comment as GitHub reports it; NULL until the user has ever acted.
    last_user_action_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Why this PR concerns the account; author beats assignee beats reviewer at sync time.
    involvement: Mapped[str] = mapped_column(
        String(24), nullable=False, default=InboxInvolvement.REVIEWER, server_default="reviewer"
    )
    last_github_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # The in-app AI review covering this PR, when one was ever started from the inbox.
    linked_review_id: Mapped[int | None] = mapped_column(
        ForeignKey("code_reviews.id", ondelete="SET NULL"), nullable=True, index=True
    )
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
