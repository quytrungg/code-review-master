"""cross-review finding search: the normalised key on review_threads

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-12

Adds `review_threads.norm_key` and backfills it from each AI thread's first assistant message. The
normaliser is copied into this file on purpose: a migration must keep doing what it did the day it
ran, even if `services/finding_search.normalise` changes later. PII: finding prose, not personal
data (the same text already lives in `thread_messages`).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEVERITY = {"critical", "high", "medium", "low", "severity", "blocker", "nit"}
_WORD_RE = re.compile(r"[a-z0-9]+")
_CODE_SPAN_RE = re.compile(r"`[^`]*`")
_MARKUP_RE = re.compile(r"[*_#>\[\]()|~]")


def _normalise(text: str | None) -> str:
    """Frozen copy of `finding_search.normalise` as it was in revision 0021."""
    cleaned = _CODE_SPAN_RE.sub(" ", text or "")
    cleaned = _MARKUP_RE.sub(" ", cleaned).lower()
    words = _WORD_RE.findall(cleaned)
    while words and words[0] in _SEVERITY:
        words.pop(0)
    return " ".join(words[:12])[:255]


def upgrade() -> None:
    with op.batch_alter_table("review_threads") as batch:
        batch.add_column(sa.Column("norm_key", sa.String(255), nullable=True))
        batch.create_index("ix_review_threads_norm_key", ["norm_key"])

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT t.id AS thread_id, m.content AS content "
            "FROM review_threads t "
            "JOIN thread_messages m ON m.thread_id = t.id "
            "WHERE t.origin IN ('AI_GENERATED', 'CHECK') AND m.role = 'assistant' "
            "ORDER BY t.id, m.id"
        )
    )
    updates: dict[int, str] = {}
    for row in rows:
        # The first assistant message is the finding; later ones are discussion answers.
        if row.thread_id not in updates:
            key = _normalise(row.content)
            if key:
                updates[row.thread_id] = key
    for thread_id, key in updates.items():
        connection.execute(
            sa.text("UPDATE review_threads SET norm_key = :key WHERE id = :id"),
            {"key": key, "id": thread_id},
        )


def downgrade() -> None:
    with op.batch_alter_table("review_threads") as batch:
        batch.drop_index("ix_review_threads_norm_key")
        batch.drop_column("norm_key")
