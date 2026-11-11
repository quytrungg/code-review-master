"""linked review watches

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-11

Adds `review_watches` (one row per account and change request) and the three columns on
`code_reviews` that make a review a delta of another one: `parent_review_id`, `watch_id` and
`trigger`. Nothing is backfilled: an existing review has no parent and no watch, and
`UNIQUE(watch_id, commit_id)` treats NULL watch ids as distinct, so manual reviews are unaffected.

`phase_21_plan.md` reserves 0013 for its own table, which is why that revision carries a note about
it; 0014 is the next free number after the ledger revision that actually shipped.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_watches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pr_url", sa.Text(), nullable=False),
        sa.Column("vcs", sa.String(16), nullable=False, server_default="github"),
        sa.Column("repo_full_name", sa.Text(), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("skill_foundation", sa.Text(), nullable=True),
        sa.Column("model_used", sa.Text(), nullable=True),
        sa.Column("last_seen_commit_id", sa.Text(), nullable=True),
        sa.Column(
            "last_review_id",
            sa.Integer(),
            sa.ForeignKey("code_reviews.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "pr_url", name="uq_review_watches_user_pr"),
    )
    op.create_index("ix_review_watches_user_id", "review_watches", ["user_id"])
    op.create_index(
        "ix_review_watches_last_checked_at", "review_watches", ["last_checked_at"]
    )

    # batch_alter_table so SQLite (tests, local file databases) and PostgreSQL both apply: adding a
    # foreign-keyed column is a table rebuild on SQLite.
    with op.batch_alter_table("code_reviews") as batch:
        batch.add_column(sa.Column("parent_review_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("watch_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("trigger", sa.String(16), nullable=True))
        batch.create_foreign_key(
            "fk_code_reviews_parent_review_id",
            "code_reviews",
            ["parent_review_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_code_reviews_watch_id",
            "review_watches",
            ["watch_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_unique_constraint(
            "uq_code_reviews_watch_commit", ["watch_id", "commit_id"]
        )
        batch.create_index("ix_code_reviews_parent_review_id", ["parent_review_id"])
        batch.create_index("ix_code_reviews_watch_id", ["watch_id"])


def downgrade() -> None:
    with op.batch_alter_table("code_reviews") as batch:
        batch.drop_index("ix_code_reviews_watch_id")
        batch.drop_index("ix_code_reviews_parent_review_id")
        batch.drop_constraint("uq_code_reviews_watch_commit", type_="unique")
        batch.drop_constraint("fk_code_reviews_watch_id", type_="foreignkey")
        batch.drop_constraint("fk_code_reviews_parent_review_id", type_="foreignkey")
        batch.drop_column("trigger")
        batch.drop_column("watch_id")
        batch.drop_column("parent_review_id")

    op.drop_index("ix_review_watches_last_checked_at", table_name="review_watches")
    op.drop_index("ix_review_watches_user_id", table_name="review_watches")
    op.drop_table("review_watches")
