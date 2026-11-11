"""inbox involvement: author/assignee rows

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-11

Adds `cached_prs.involvement` (`reviewer` | `assignee` | `author`): the inbox now also surfaces
PRs authored by or assigned to the user, and the role lets the UI tell a review request from an
own PR. Rows the legacy queries discovered keep the default `reviewer`; sync recomputes the role
on every run.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch_alter_table so SQLite (tests, local file databases) and PostgreSQL both apply.
    with op.batch_alter_table("cached_prs") as batch:
        batch.add_column(
            sa.Column("involvement", sa.String(24), nullable=False, server_default="reviewer")
        )


def downgrade() -> None:
    with op.batch_alter_table("cached_prs") as batch:
        batch.drop_column("involvement")
