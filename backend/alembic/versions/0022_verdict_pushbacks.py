"""verdict push-backs: the reviewer's argument and the model's answer

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-12

One row per push-back against the AI's suggested verdict. Nothing is backfilled: the table starts
empty because the argument over an opinion only exists from now on. PII: reviewer-authored prose,
the same class as `thread_messages` content.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verdict_pushbacks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("argument", sa.Text(), nullable=False),
        sa.Column("previous_verdict", sa.String(length=32), nullable=True),
        sa.Column("previous_confidence", sa.Integer(), nullable=True),
        sa.Column("agrees", sa.Boolean(), nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["review_id"], ["code_reviews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_verdict_pushbacks_review_id", "verdict_pushbacks", ["review_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_verdict_pushbacks_review_id", table_name="verdict_pushbacks")
    op.drop_table("verdict_pushbacks")
