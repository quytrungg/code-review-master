"""One pending Claude sign-in.

The PKCE verifier must survive between "start" and "complete" but must not be trusted from the
browser, so it is stored here encrypted, keyed by the OAuth `state`, and deleted when the flow
finishes. Expired rows are purged on the next start; nothing reads this table outside the flow.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow
from app.db.types import EncryptedText


class ClaudeOAuthState(Base):
    __tablename__ = "claude_oauth_states"
    __table_args__ = (UniqueConstraint("state", name="uq_claude_oauth_states_state"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    # PKCE code_verifier: a secret for the token exchange, so encrypted like a credential.
    verifier: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
