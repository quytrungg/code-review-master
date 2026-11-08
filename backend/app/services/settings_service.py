from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.settings import Settings as SettingsRow


def get_or_create(db: Session, user_id: int) -> SettingsRow:
    """Fetch one user's settings row, creating it on first use.

    The row only stores which credentials are active, so "defaults" simply means "nothing
    selected yet". One row per account; two accounts never share a selection.
    """
    row = db.scalars(select(SettingsRow).where(SettingsRow.user_id == user_id)).first()
    if row is None:
        row = SettingsRow(user_id=user_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row
