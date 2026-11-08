"""encrypt provider credentials

Revision ID: 0011
Revises: 0009
Create Date: 2026-11-08

Data-only revision: `version_control_keys.token` and `llm_keys.api_key` are still `Text`, but
their contents become authenticated Fernet ciphertext (`enc:v1:` envelope) with the key held in
`CREDENTIALS_ENCRYPTION_KEY`. No DDL, so PostgreSQL and SQLite behave identically.

Numbered 0011 rather than 0010 because the unimplemented phase 15 plan
(`docs/plans/phase_15_plan.md`) reserved `0010_review_events` at the time; that reservation was
dropped when phase 15 landed as `0012_review_events` (every database was already stamped 0011, so
a revision inserted behind head could never run).

Upgrade refuses to run when plaintext rows exist and no key is configured: a revision that
claims encryption must not leave clear text behind. Downgrade decrypts and needs the same key set
that produced the ciphertext.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.db.encryption import encrypt_plaintext  # noqa: PLC0415 - imported after path setup

    encrypt_plaintext(op.get_bind())


def downgrade() -> None:
    from app.db.encryption import decrypt_all  # noqa: PLC0415 - imported after path setup

    decrypt_all(op.get_bind())
