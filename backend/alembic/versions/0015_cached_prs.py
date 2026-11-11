"""cached PR inbox

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-11

Adds `cached_prs`: one row per (account, pull request) the PR inbox tracks. The unique key and the
indexes are scoped by `user_id` on purpose — two accounts may cache the same GitHub PR, and the
ownership rule (an unknown id is a 404, never a 403) only works when rows never cross accounts.
Nothing is backfilled: the cache fills on the first `POST /api/inbox/sync`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cached_prs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("github_pr_id", sa.BigInteger(), nullable=False),
        sa.Column("repo_owner", sa.Text(), nullable=False),
        sa.Column("repo_name", sa.Text(), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("pr_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("author_username", sa.Text(), nullable=False),
        sa.Column("author_avatar_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="needs_review"),
        sa.Column("has_unread_replies", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("unread_replies_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_user_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_github_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "linked_review_id",
            sa.Integer(),
            sa.ForeignKey("code_reviews.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "repo_owner", "repo_name", "pr_number", name="uq_cached_prs_user_pr"
        ),
    )
    op.create_index("ix_cached_prs_user_id", "cached_prs", ["user_id"])
    op.create_index("ix_cached_prs_status", "cached_prs", ["user_id", "status"])
    op.create_index(
        "ix_cached_prs_github_pr_id", "cached_prs", ["user_id", "github_pr_id"]
    )
    op.create_index("ix_cached_prs_linked_review_id", "cached_prs", ["linked_review_id"])


def downgrade() -> None:
    op.drop_index("ix_cached_prs_linked_review_id", table_name="cached_prs")
    op.drop_index("ix_cached_prs_github_pr_id", table_name="cached_prs")
    op.drop_index("ix_cached_prs_status", table_name="cached_prs")
    op.drop_index("ix_cached_prs_user_id", table_name="cached_prs")
    op.drop_table("cached_prs")
