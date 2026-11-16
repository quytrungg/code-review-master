"""code_reviews.approval_published: did this review approve the pull request?

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-12

`verdict` records the event of the last apply, so a replies-only apply sets it without publishing a
review — it cannot tell us whether an approval happened. This column can, and phase 45 needs it to
allow an approval after a COMMENT review without allowing a duplicate one.

Backfill is narrow on purpose: only rows that match the one shape the old code could approve in — a
review URL, `verdict = 'APPROVE'`, and no published AI round 1. Nothing else is guessed at.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BACKFILL = """
UPDATE code_reviews SET approval_published = true
WHERE github_review_url IS NOT NULL
  AND verdict = 'APPROVE'
  AND NOT EXISTS (
    SELECT 1 FROM review_threads t
    JOIN thread_rounds r ON r.thread_id = t.id
    WHERE t.review_id = code_reviews.id
      AND t.origin = 'AI_GENERATED'
      AND r.round_number = 1
      AND r.status = 'published'
  )
"""


def upgrade() -> None:
    with op.batch_alter_table("code_reviews") as batch:
        batch.add_column(
            sa.Column(
                "approval_published", sa.Boolean(), nullable=False, server_default=sa.text("false")
            )
        )
    op.execute(_BACKFILL)


def downgrade() -> None:
    with op.batch_alter_table("code_reviews") as batch:
        batch.drop_column("approval_published")
