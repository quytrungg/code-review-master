from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.settings import Settings as SettingsRow

# The registry of known beta flags. One source of truth: `GET /api/settings` exposes it as
# `beta_registry` so the Settings page renders from data and never hardcodes flag ids, and the
# PUT branch rejects any id not listed here. Adding a flag means adding one entry.
BETA_FEATURES: list[dict[str, str]] = [
    {
        "id": "push_back_lessons",
        "label": "Push-back lessons",
        "description": (
            "When you push back on a finding, offer to record the lesson as a rule "
            "in a skill foundation."
        ),
    },
]

BETA_FEATURE_IDS = frozenset(entry["id"] for entry in BETA_FEATURES)


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


def beta_enabled(db: Session, user_id: int, flag: str) -> bool:
    """Is this beta flag switched on for this account?

    False for an unknown flag id, an account with no settings row yet, or an unset flag —
    services gate on this without worrying which of the three it is. Read-only: unlike
    `get_or_create` it never writes, so asking never provisions a row.
    """
    if flag not in BETA_FEATURE_IDS:
        return False
    row = db.scalars(select(SettingsRow).where(SettingsRow.user_id == user_id)).first()
    if row is None:
        return False
    return bool((row.beta_features or {}).get(flag, False))
