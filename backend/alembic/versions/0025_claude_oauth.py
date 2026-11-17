"""Claude sign-in: an OAuth credential beside the Claude API key.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-17

`llm_keys` already holds every provider secret, so a Claude sign-in is the same row with a
different auth type: the access token stays in `api_key`, and the refresh token and expiry live
beside it. `claude_oauth_states` carries the PKCE verifier between "start" and "complete" and is
deleted as soon as a flow finishes.

Existing rows are API keys: the server default backfills them, so no data is rewritten.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("llm_keys") as batch:
        batch.add_column(
            sa.Column(
                "auth_type",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'api_key'"),
            )
        )
        batch.add_column(sa.Column("refresh_token", sa.Text(), nullable=True))
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "claude_oauth_states",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("verifier", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("state", name="uq_claude_oauth_states_state"),
    )
    op.create_index(
        "ix_claude_oauth_states_user_id", "claude_oauth_states", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_claude_oauth_states_user_id", table_name="claude_oauth_states")
    op.drop_table("claude_oauth_states")
    with op.batch_alter_table("llm_keys") as batch:
        batch.drop_column("expires_at")
        batch.drop_column("refresh_token")
        batch.drop_column("auth_type")
