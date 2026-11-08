"""thread rounds, origins and external messages

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-08

Adds everything Phase 13 needs to treat AI findings and pre-existing GitHub PR comments as one
kind of thread: `origin`, `github_root_comment_id`, `original_author`, `current_round` and
`thread_status` on `review_threads`; a `thread_rounds` table; and `round_number`, `is_external`
and `github_comment_id` on `thread_messages`.

Existing threads are backfilled rather than dropped: every current thread gets round 1 holding its
last assistant message, published when its review was applied and drafting otherwise.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("review_threads") as batch:
        batch.add_column(
            sa.Column(
                "origin", sa.String(16), nullable=False, server_default="AI_GENERATED"
            )
        )
        batch.add_column(sa.Column("github_root_comment_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("original_author", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("current_round", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column("thread_status", sa.String(24), nullable=False, server_default="active")
        )
    op.create_index(
        "ix_review_threads_github_root_comment_id",
        "review_threads",
        ["github_root_comment_id"],
    )

    op.create_table(
        "thread_rounds",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("review_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("round_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("inbound_github_comment_id", sa.BigInteger(), nullable=True),
        sa.Column("inbound_author", sa.Text(), nullable=True),
        sa.Column("inbound_body", sa.Text(), nullable=True),
        sa.Column("final_summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="drafting"),
        sa.Column("published_github_comment_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_thread_rounds_thread_id", "thread_rounds", ["thread_id"])

    with op.batch_alter_table("thread_messages") as batch:
        batch.add_column(
            sa.Column("round_number", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column(
                "is_external", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch.add_column(sa.Column("github_comment_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("author", sa.Text(), nullable=True))
    op.create_index(
        "ix_thread_messages_github_comment_id", "thread_messages", ["github_comment_id"]
    )

    # One round per existing thread, carrying its last assistant conclusion. Nothing is deleted.
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO thread_rounds
                (thread_id, round_number, final_summary, status, created_at, updated_at)
            SELECT t.id, 1,
                   (SELECT m.content FROM thread_messages m
                     WHERE m.thread_id = t.id AND m.role = 'assistant'
                     ORDER BY m.id DESC LIMIT 1),
                   CASE WHEN r.status = 'applied' THEN 'published' ELSE 'drafting' END,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
              FROM review_threads t
              JOIN code_reviews r ON r.id = t.review_id
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_thread_messages_github_comment_id", table_name="thread_messages")
    with op.batch_alter_table("thread_messages") as batch:
        batch.drop_column("author")
        batch.drop_column("github_comment_id")
        batch.drop_column("is_external")
        batch.drop_column("round_number")

    op.drop_index("ix_thread_rounds_thread_id", table_name="thread_rounds")
    op.drop_table("thread_rounds")

    op.drop_index(
        "ix_review_threads_github_root_comment_id", table_name="review_threads"
    )
    with op.batch_alter_table("review_threads") as batch:
        batch.drop_column("thread_status")
        batch.drop_column("current_round")
        batch.drop_column("original_author")
        batch.drop_column("github_root_comment_id")
        batch.drop_column("origin")
