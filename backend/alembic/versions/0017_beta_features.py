"""beta features: per-user flag registry storage

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-11

Adds `settings.beta_features` (JSON, `{}` by default): one per-user map of beta flag id →
enabled. The registry of known flags lives in `settings_service.BETA_FEATURES`; unknown ids are
rejected at the API boundary and never persist.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch_alter_table so SQLite (tests, local file databases) and PostgreSQL both apply.
    with op.batch_alter_table("settings") as batch:
        batch.add_column(
            sa.Column("beta_features", sa.JSON(), nullable=False, server_default="{}")
        )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch:
        batch.drop_column("beta_features")
