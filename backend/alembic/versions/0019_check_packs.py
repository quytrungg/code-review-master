"""deterministic pre-pass packs: which check packs an account has enabled

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-12

Adds `settings.check_packs`, a JSON list of pack ids from `services/checks_service.PACKS`.
`[]` is the default and means "checks off": the packs are opt-in, so a database that predates this
revision behaves exactly as before. PII: not personal data — pack ids only.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch:
        batch.add_column(
            sa.Column("check_packs", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch:
        batch.drop_column("check_packs")
