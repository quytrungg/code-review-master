from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow


class ReviewStatus:
    RUNNING = "running"
    DRAFT = "draft"
    IN_DISCUSSION = "in_discussion"
    APPLIED = "applied"
    FAILED = "failed"

    ALL = (RUNNING, DRAFT, IN_DISCUSSION, APPLIED, FAILED)


class ReviewVerdict:
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    COMMENT = "COMMENT"

    ALL = (APPROVE, REQUEST_CHANGES, COMMENT)


class MessageRole:
    ASSISTANT = "assistant"
    USER = "user"
    SYSTEM = "system"

    ALL = (ASSISTANT, USER, SYSTEM)


class ThreadOrigin:
    """Where a thread came from: our model, or the pull request's own comments."""

    AI_GENERATED = "AI_GENERATED"
    GITHUB_EXISTING = "GITHUB_EXISTING"

    ALL = (AI_GENERATED, GITHUB_EXISTING)


class ThreadStatus:
    """Coarse thread state, used by the workspace filter bar."""

    ACTIVE = "active"
    NEEDS_RESPONSE = "needs_response"
    APPLIED = "applied"
    RESOLVED = "resolved"

    ALL = (ACTIVE, NEEDS_RESPONSE, APPLIED, RESOLVED)


class RoundStatus:
    """One exchange within a thread: drafting → pending_apply → published | resolved_no_reply."""

    DRAFTING = "drafting"
    PENDING_APPLY = "pending_apply"
    PUBLISHED = "published"
    RESOLVED_NO_REPLY = "resolved_no_reply"

    ALL = (DRAFTING, PENDING_APPLY, PUBLISHED, RESOLVED_NO_REPLY)
    # Rounds the apply button has work for.
    PENDING = (DRAFTING, PENDING_APPLY)


class CodeReview(Base):
    __tablename__ = "code_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pr_url: Mapped[str] = mapped_column(Text, nullable=False)
    # Which version-control host this review belongs to: "github" or "gitlab".
    vcs: Mapped[str] = mapped_column(
        String(16), nullable=False, default="github", server_default="github"
    )
    pr_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repo_full_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    commit_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which Core Skill Foundation this review was generated with (folder id).
    skill_foundation: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=ReviewStatus.DRAFT)
    verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # What the model thinks should happen, and how sure it is (0-100).
    suggested_verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence_percentage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # One line explaining the latest opinion; refreshed after each discussion round.
    suggested_verdict_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_review_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    threads: Mapped[list["ReviewThread"]] = relationship(
        back_populates="review",
        cascade="all, delete-orphan",
        order_by="ReviewThread.id",
        lazy="selectin",
    )


class ReviewThread(Base):
    __tablename__ = "review_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("code_reviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    diff_hunk: Mapped[str] = mapped_column(Text, nullable=False, default="")
    side: Mapped[str] = mapped_column(String(8), nullable=False, default="RIGHT")
    # AI_GENERATED (our model) or GITHUB_EXISTING (imported from the pull request).
    origin: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ThreadOrigin.AI_GENERATED,
        server_default=ThreadOrigin.AI_GENERATED,
    )
    # Root PR comment: set at ingest for existing threads, backfilled after Round 1 apply for AI ones.
    github_root_comment_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    original_author: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_round: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    thread_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=ThreadStatus.ACTIVE, server_default=ThreadStatus.ACTIVE
    )
    # Filled by the pre-publish summarisation pass.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    dropped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    review: Mapped[CodeReview] = relationship(back_populates="threads")
    messages: Mapped[list["ThreadMessage"]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="ThreadMessage.id",
        lazy="selectin",
    )
    rounds: Mapped[list["ThreadRound"]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="ThreadRound.round_number",
        lazy="selectin",
    )

    def round(self, number: int) -> "ThreadRound | None":
        for item in self.rounds:
            if item.round_number == number:
                return item
        return None


class ThreadRound(Base):
    """One inbound message (GitHub) or one outbound reply, tracked to its publication state."""

    __tablename__ = "thread_rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("review_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    inbound_github_comment_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    inbound_author: Mapped[str | None] = mapped_column(Text, nullable=True)
    inbound_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The text published to GitHub for this round.
    final_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=RoundStatus.DRAFTING,
        server_default=RoundStatus.DRAFTING,
    )
    published_github_comment_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    thread: Mapped[ReviewThread] = relationship(back_populates="rounds")


class ThreadMessage(Base):
    __tablename__ = "thread_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("review_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # True for a comment imported from the PR, so the transcript can label its author.
    is_external: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # The PR comment id for an external message: the dedupe key across syncs.
    github_comment_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    # GitHub login of an external message's author, so each comment keeps its own attribution.
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    thread: Mapped[ReviewThread] = relationship(back_populates="messages")


class ReviewEvent(Base):
    """One persisted ingest stage for a review.

    Progress used to live in process memory; it is a table now so a second instance (or a cold
    start) can replay a review's history to a late SSE client. `seq` is per review and dense,
    which is what the browser de-duplicates on.
    """

    __tablename__ = "review_events"
    __table_args__ = (
        UniqueConstraint("review_id", "seq", name="uq_review_events_review_seq"),
        Index("ix_review_events_review_seq", "review_id", "seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("code_reviews.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[str] = mapped_column(String(8), nullable=False, default="info")
    progress: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    terminal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
