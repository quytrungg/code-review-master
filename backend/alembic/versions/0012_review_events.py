"""review progress events

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-08

Adds `review_events`, the per-review progress log that replaces the in-process SSE bus. Serverless
deployments run ingest in one invocation and the browser streams from another, so event history
must live in the database; a cold start replays it instead of losing it.

Numbered 0012, not the `0010` slot 0011 reserved: every database already stamped 0012's parent
(0011) is at head, and a revision inserted behind head would never run there.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "review_id",
            sa.Integer(),
            sa.ForeignKey("code_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("level", sa.String(8), nullable=False, server_default="info"),
        sa.Column("progress", sa.SmallInteger(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("terminal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("review_id", "seq", name="uq_review_events_review_seq"),
    )
    op.create_index("ix_review_events_review_seq", "review_events", ["review_id", "seq"])


def downgrade() -> None:
    op.drop_index("ix_review_events_review_seq", table_name="review_events")
    op.drop_table("review_events")
