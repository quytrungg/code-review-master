"""ollama cloud: api key + mode

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-07
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("ollama_api_key", sa.Text(), nullable=True))
    op.add_column(
        "settings",
        sa.Column("ollama_mode", sa.String(length=16), server_default="cloud", nullable=False),
    )
    # Rows that were configured before this revision were talking to a local daemon;
    # keep them working instead of silently switching them to the hosted API.
    op.execute(
        "UPDATE settings SET ollama_mode = 'local' "
        "WHERE ollama_base_url IS NOT NULL AND ollama_base_url NOT LIKE 'https://ollama.com%'"
    )


def downgrade() -> None:
    op.drop_column("settings", "ollama_mode")
    op.drop_column("settings", "ollama_api_key")
