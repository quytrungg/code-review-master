"""verdict rationale for re-evaluated AI opinions

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-08

The suggested verdict is now refreshed after each discussion round, so it carries a one-line
reason. Existing reviews keep NULL and fall back to the plain verdict.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("code_reviews") as batch:
        batch.add_column(sa.Column("suggested_verdict_note", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("code_reviews") as batch:
        batch.drop_column("suggested_verdict_note")
