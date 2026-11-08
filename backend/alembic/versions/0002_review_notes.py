"""code_reviews.notes for ingestion warnings

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-07
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("code_reviews", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("code_reviews", "notes")
