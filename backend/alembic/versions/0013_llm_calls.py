"""llm call ledger and monthly budget caps

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-09

Adds `llm_calls` — one row per provider call, counts and latency only, never prompt or completion
text — and the two soft budget caps on `settings`. Nothing is backfilled: the table starts empty
and a review older than this revision simply has no usage line until its next call.

`phase_21_plan.md` reserves the number 0013 for its own `skill_foundations` table, but that phase is
a design record with no code and head was 0012; a revision inserted behind head would never run
(the note in `0012` covers the same constraint).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "review_id",
            sa.Integer(),
            sa.ForeignKey("code_reviews.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("review_threads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error_class", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_llm_calls_review_id_created", "llm_calls", ["review_id", "created_at"]
    )
    op.create_index(
        "ix_llm_calls_analytics", "llm_calls", ["created_at", "provider", "model", "purpose"]
    )

    # batch_alter_table so SQLite (tests, local file databases) and PostgreSQL both apply.
    with op.batch_alter_table("settings") as batch:
        batch.add_column(sa.Column("monthly_token_budget", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("monthly_dollar_budget", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch:
        batch.drop_column("monthly_dollar_budget")
        batch.drop_column("monthly_token_budget")

    op.drop_index("ix_llm_calls_analytics", table_name="llm_calls")
    op.drop_index("ix_llm_calls_review_id_created", table_name="llm_calls")
    op.drop_table("llm_calls")
