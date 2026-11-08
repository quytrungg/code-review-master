"""Maintenance passes over the encrypted credential columns.

Deliberately built on Core SQL rather than the ORM: `EncryptedText` decrypts on load, so a
model-based pass could not tell whether a stored value was already ciphertext. That prefix check
is what makes the backfill, the rotation and the copy script idempotent.

Every pass works on the two `(table, column)` pairs below, which are literals in this module —
no SQL fragment is ever built from input.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.core.crypto import (
    CredentialKeyError,
    decrypt_secret,
    encrypt_secret,
    is_encrypted,
)

logger = logging.getLogger(__name__)

CREDENTIAL_COLUMNS = (("version_control_keys", "token"), ("llm_keys", "api_key"))


def _rows(connection: Connection, table: str, column: str) -> list[tuple[int, str | None]]:
    result = connection.execute(sa.text(f"SELECT id, {column} FROM {table} ORDER BY id"))
    return [(row[0], row[1]) for row in result]


def _count(connection: Connection, table: str, column: str) -> int:
    statement = sa.text(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NOT NULL")
    return int(connection.execute(statement).scalar_one())


def _write(connection: Connection, table: str, column: str, row_id: int, value: str) -> None:
    connection.execute(
        sa.text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
        {"value": value, "id": row_id},
    )


def encrypt_plaintext(connection: Connection) -> dict[str, int]:
    """Encrypt every stored value that is still plaintext; returns rows changed per table.

    Raises `CredentialKeyError` when rows need encrypting and no key is configured, so an
    upgrade cannot claim "encrypted at rest" while leaving clear text behind.
    """
    counts: dict[str, int] = {}
    for table, column in CREDENTIAL_COLUMNS:
        pending = [
            (row_id, value)
            for row_id, value in _rows(connection, table, column)
            if value and not is_encrypted(value)
        ]
        if pending and not get_settings().encryption_keys:
            raise CredentialKeyError(
                f"{len(pending)} stored credential(s) in {table}.{column} are still plaintext. "
                "Set CREDENTIALS_ENCRYPTION_KEY (see `python scripts/generate_encryption_key.py`) "
                "and run the upgrade again."
            )
        for row_id, value in pending:
            _write(connection, table, column, row_id, encrypt_secret(value))
        counts[table] = len(pending)
        if pending:
            logger.info("Encrypted %s plaintext value(s) in %s.%s", len(pending), table, column)
    return counts


def decrypt_all(connection: Connection) -> dict[str, int]:
    """Restore plaintext, for `alembic downgrade`. The key set must still be configured."""
    counts: dict[str, int] = {}
    for table, column in CREDENTIAL_COLUMNS:
        encrypted = [
            (row_id, value)
            for row_id, value in _rows(connection, table, column)
            if is_encrypted(value)
        ]
        for row_id, value in encrypted:
            _write(connection, table, column, row_id, decrypt_secret(value))
        counts[table] = len(encrypted)
        if encrypted:
            logger.info("Decrypted %s value(s) in %s.%s", len(encrypted), table, column)
    return counts


def reencrypt_all(connection: Connection, *, dry_run: bool = False) -> dict[str, int]:
    """Rewrite every row with the active key (first in the key set).

    Used by the rotation script: run with `new,old` configured, then drop the old key. Raises if
    any row cannot be decrypted with the current key set, before writing anything.
    """
    counts: dict[str, int] = {}
    for table, column in CREDENTIAL_COLUMNS:
        rows = [(row_id, value) for row_id, value in _rows(connection, table, column) if value]
        for row_id, value in rows:
            plaintext = decrypt_secret(value)
            if not dry_run:
                _write(connection, table, column, row_id, encrypt_secret(plaintext))
        counts[table] = len(rows)
    return counts


def plaintext_count(connection: Connection) -> int:
    """Rows still stored without the envelope; zero after a successful upgrade."""
    return sum(
        1
        for table, column in CREDENTIAL_COLUMNS
        for _, value in _rows(connection, table, column)
        if value and not is_encrypted(value)
    )


def log_startup_report() -> None:
    """Log the encryption state after migrations. Counts and configuration only — never values."""
    from app.db.session import SessionLocal  # noqa: PLC0415 - keeps the revision import light

    db = SessionLocal()
    try:
        connection = db.connection()
        total = sum(_count(connection, table, column) for table, column in CREDENTIAL_COLUMNS)
        plaintext = plaintext_count(connection)
    except Exception:  # noqa: BLE001 - a reporting failure must not block startup
        logger.exception("Could not inspect stored credentials")
        return
    finally:
        db.close()

    keys = get_settings().encryption_keys
    if total and not keys:
        logger.error(
            "Credential encryption is not configured but %s credential row(s) exist. "
            "Set CREDENTIALS_ENCRYPTION_KEY and restart.",
            total,
        )
    elif plaintext:
        logger.warning(
            "Credential encryption: %s row(s) still plaintext; run `alembic upgrade head`.",
            plaintext,
        )
    else:
        logger.info(
            "Credential encryption: keys=%s rows=%s plaintext=%s",
            len(keys),
            total,
            plaintext,
        )
