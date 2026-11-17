"""Which finished reviews has the operator not looked at yet?

The queue is derived, not stored twice: `CodeReview.has_unread` says a row left `running` while its
`completed_seen_at` was still `NULL`. This module only counts those rows and acknowledges one.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.review import CodeReview, ReviewStatus


def _unread_clause(user_id: int):
    return (
        CodeReview.user_id == user_id,
        CodeReview.status != ReviewStatus.RUNNING,
        CodeReview.completed_seen_at.is_(None),
    )


def unread_count(db: Session, user_id: int) -> int:
    """How many finished reviews on this account have not been opened."""
    total = db.scalar(
        select(func.count()).select_from(CodeReview).where(*_unread_clause(user_id))
    )
    return int(total or 0)


def mark_seen(db: Session, review: CodeReview) -> CodeReview:
    """Acknowledge this review's finished state; a `running` row is left alone.

    Early acknowledgement would swallow the notification the job is about to produce, so a
    `running` review is returned unchanged rather than marked. The call is idempotent: the stored
    timestamp is never moved forward by a second visit.
    """
    if review.status == ReviewStatus.RUNNING or review.completed_seen_at is not None:
        return review
    review.completed_seen_at = utcnow()
    db.commit()
    db.refresh(review)
    return review
