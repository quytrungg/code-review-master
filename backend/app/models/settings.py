from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class Settings(Base):
    """One row per user, holding that user's *active* credentials.

    The secrets themselves live in `version_control_keys` and `llm_keys`; this table only
    references the two the operator currently wants to use. Deleting a key sets the pointer
    back to NULL instead of cascading, so losing a credential never removes unrelated data.
    """

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    version_control_key_id: Mapped[int | None] = mapped_column(
        ForeignKey("version_control_keys.id", ondelete="SET NULL"), nullable=True
    )
    llm_key_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_keys.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
