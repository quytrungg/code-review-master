"""skill foundation column

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-07
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("code_reviews", sa.Column("skill_foundation", sa.Text(), nullable=True))
    # Before this revision there was exactly one foundation, so backfill it.
    op.execute(
        "UPDATE code_reviews SET skill_foundation = 'code-review' WHERE skill_foundation IS NULL"
    )


def downgrade() -> None:
    op.drop_column("code_reviews", "skill_foundation")
