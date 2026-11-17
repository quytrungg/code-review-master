"""code_reviews.completed_seen_at: has the operator looked at this finished review?

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-17

A review that leaves `running` while the operator is on another page is a notification: the row
gets a dot and the navbar counts it. One nullable timestamp is the whole state — `NULL` means
"finished and not looked at", a value means acknowledged when it was set.

Every row that was already finished before this revision is backfilled as seen: history is not
news, and opening the app after the upgrade must not light up fifty dots. `running` rows keep
`NULL`, so a job that finishes after the upgrade still notifies.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BACKFILL = """
UPDATE code_reviews SET completed_seen_at = updated_at
WHERE status <> 'running'
"""


def upgrade() -> None:
    with op.batch_alter_table("code_reviews") as batch:
        batch.add_column(sa.Column("completed_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(_BACKFILL)


def downgrade() -> None:
    with op.batch_alter_table("code_reviews") as batch:
        batch.drop_column("completed_seen_at")
