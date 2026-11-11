"""One lesson recorded from a pushed-back finding, applied to a skill foundation.

Written only after the reviewer approves it in the push-back modal (beta flag
`push_back_lessons`): the markdown file lands in the chosen foundation and this row is the
attribution link back to the finding that produced it. Reviewer-approved text only — never a
prompt, a diff, or a credential.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class SkillLesson(Base):
    __tablename__ = "skill_lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    review_id: Mapped[int] = mapped_column(
        ForeignKey("code_reviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("review_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Which foundation the lesson file was written into, and where inside it.
    foundation: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
