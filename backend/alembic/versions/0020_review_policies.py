"""standing review policies: one row per repo glob, and the tick that applies it

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-12

Adds `review_policies`, `code_reviews.policy_id` (the policy that started the review, which is
also how `max_active` counts) and `cached_prs.policy_claim_at` (the compare-and-set claim that
keeps two ticks from reviewing one PR twice). PII: none of these columns hold personal data.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_policies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("repo_pattern", sa.Text(), nullable=False),
        sa.Column(
            "involvement", sa.String(24), nullable=False, server_default="reviewer"
        ),
        sa.Column("model_used", sa.Text(), nullable=False),
        sa.Column("skill_foundation", sa.Text(), nullable=True),
        sa.Column("max_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_review_policies_user_id", "review_policies", ["user_id"])
    op.create_index("ix_review_policies_last_run_at", "review_policies", ["last_run_at"])

    with op.batch_alter_table("code_reviews") as batch:
        batch.add_column(sa.Column("policy_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_code_reviews_policy_id",
            "review_policies",
            ["policy_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_code_reviews_policy_id", ["policy_id"])

    with op.batch_alter_table("cached_prs") as batch:
        batch.add_column(sa.Column("policy_claim_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("cached_prs") as batch:
        batch.drop_column("policy_claim_at")

    with op.batch_alter_table("code_reviews") as batch:
        batch.drop_index("ix_code_reviews_policy_id")
        batch.drop_constraint("fk_code_reviews_policy_id", type_="foreignkey")
        batch.drop_column("policy_id")

    op.drop_index("ix_review_policies_last_run_at", table_name="review_policies")
    op.drop_index("ix_review_policies_user_id", table_name="review_policies")
    op.drop_table("review_policies")
