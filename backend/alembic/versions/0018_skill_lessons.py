"""push-back lessons: attribution for rules written from rejected findings

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-11

Adds `skill_lessons`: one row per lesson the reviewer applied to a skill foundation from a pushed
back finding (initiative 6, beta-gated by `settings.beta_features.push_back_lessons` from 0017).
The lesson text itself lives in the foundation's markdown; this table is the link back to the
thread that produced it. Nothing is stored here that is not already in the thread.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skill_lessons",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "review_id",
            sa.Integer(),
            sa.ForeignKey("code_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("review_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("foundation", sa.String(64), nullable=False),
        sa.Column("path", sa.String(255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_skill_lessons_user_id", "skill_lessons", ["user_id"])
    op.create_index("ix_skill_lessons_review_id", "skill_lessons", ["review_id"])
    op.create_index("ix_skill_lessons_thread_id", "skill_lessons", ["thread_id"])


def downgrade() -> None:
    op.drop_table("skill_lessons")
