"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-07
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("github_token", sa.Text(), nullable=True),
        sa.Column("claude_api_key", sa.Text(), nullable=True),
        sa.Column("ollama_base_url", sa.Text(), server_default="http://localhost:11434", nullable=False),
        sa.Column("ollama_model", sa.Text(), server_default="llama3", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "code_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("pr_url", sa.Text(), nullable=False),
        sa.Column("pr_title", sa.Text(), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("repo_full_name", sa.Text(), nullable=True),
        sa.Column("commit_id", sa.Text(), nullable=True),
        sa.Column("model_used", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("github_review_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_code_reviews_created_at", "code_reviews", ["created_at"])

    op.create_table(
        "review_threads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("diff_hunk", sa.Text(), server_default="", nullable=False),
        sa.Column("side", sa.String(length=8), server_default="RIGHT", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["review_id"], ["code_reviews.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_review_threads_review_id", "review_threads", ["review_id"])

    op.create_table(
        "thread_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["review_threads.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_thread_messages_thread_id", "thread_messages", ["thread_id"])


def downgrade() -> None:
    op.drop_index("ix_thread_messages_thread_id", table_name="thread_messages")
    op.drop_table("thread_messages")
    op.drop_index("ix_review_threads_review_id", table_name="review_threads")
    op.drop_table("review_threads")
    op.drop_index("ix_code_reviews_created_at", table_name="code_reviews")
    op.drop_table("code_reviews")
    op.drop_table("settings")
