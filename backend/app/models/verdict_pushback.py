"""One reviewer push-back against the AI's suggested verdict, and the model's answer.

The opinion on `code_reviews` is a snapshot; this table is the argument over it. A row is written
for every exchange so the workspace can show the history, and only an agreeing answer changes the
stored opinion — a disagreement records itself and leaves the verdict standing. Reviewer-authored
text plus model output only: no diff, no prompt, no credential.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class VerdictPushback(Base):
    __tablename__ = "verdict_pushbacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("code_reviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # What the reviewer wrote, verbatim and trimmed.
    argument: Mapped[str] = mapped_column(Text, nullable=False)
    # The opinion this argument was aimed at — kept even after the opinion is rewritten.
    previous_verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    previous_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # What the model decided, and the verdict it proposed afterwards.
    agrees: Mapped[bool] = mapped_column(Boolean, nullable=False)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
