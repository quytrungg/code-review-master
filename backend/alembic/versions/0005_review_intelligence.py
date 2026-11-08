"""review intelligence: verdict opinion, confidence, thread summaries

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-07
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("code_reviews", sa.Column("suggested_verdict", sa.String(length=32), nullable=True))
    op.add_column("code_reviews", sa.Column("confidence_percentage", sa.Integer(), nullable=True))
    op.add_column("review_threads", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column(
        "review_threads",
        sa.Column("dropped", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("review_threads", "dropped")
    op.drop_column("review_threads", "summary")
    op.drop_column("code_reviews", "confidence_percentage")
    op.drop_column("code_reviews", "suggested_verdict")
