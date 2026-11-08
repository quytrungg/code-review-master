"""Authenticated symmetric encryption for stored provider credentials.

The key lives in the environment (`CREDENTIALS_ENCRYPTION_KEY`) and never in the database, so an
offline copy of it — a dump, a backup, a stolen disk — does not hand over live GitHub tokens or
model-provider keys. Values are stored with an `enc:v1:` envelope: it distinguishes ciphertext
from pre-encryption plaintext, which keeps the backfill idempotent and lets a restored older
backup keep working with a warning.

Losing the key loses every stored credential; there is no recovery path by design.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings

logger = logging.getLogger(__name__)

ENVELOPE = "enc:v1:"


class CredentialError(RuntimeError):
    """The server cannot read or write a secret; always an operator-fixable configuration state."""

    status_code = 503
    default_detail = "Credential encryption failed."

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class CredentialKeyError(CredentialError):
    """No usable encryption key is configured."""

    default_detail = (
        "Credential encryption is not configured. Set CREDENTIALS_ENCRYPTION_KEY and restart."
    )


class CredentialDecryptionError(CredentialError):
    """Stored ciphertext cannot be opened with the configured key set."""

    default_detail = "Stored credentials cannot be decrypted with the configured key."


@lru_cache(maxsize=4)
def _multifernet(keys: tuple[str, ...]) -> MultiFernet:
    try:
        return MultiFernet([Fernet(key.encode()) for key in keys])
    except (ValueError, TypeError) as exc:
        raise CredentialKeyError(
            "CREDENTIALS_ENCRYPTION_KEY is not a valid Fernet key. Generate one with "
            "`python scripts/generate_encryption_key.py`."
        ) from exc


def _cipher() -> MultiFernet:
    keys = get_settings().encryption_keys
    if not keys:
        raise CredentialKeyError()
    return _multifernet(keys)


def is_encrypted(value: str | None) -> bool:
    """True when a stored value carries this scheme's envelope."""
    return bool(value) and value.startswith(ENVELOPE)


def ensure_encryption_configured() -> None:
    """Raise `CredentialKeyError` before any SQL is attempted.

    The column type would raise this on bind anyway, but SQLAlchemy wraps bind failures in a
    `StatementError`; checking first keeps the API's `503` contract and the transaction clean.
    """
    _cipher()


def encrypt_secret(value: str) -> str:
    """Encrypt with the first configured key; the nonce is fresh on every call."""
    return ENVELOPE + _cipher().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    """Decrypt a stored value.

    A value without the envelope is pre-encryption plaintext: it is returned so a database
    restored from an older backup stays usable, and the caller is told to upgrade.
    """
    if not value:
        return value
    if not is_encrypted(value):
        logger.warning("Stored credential is not encrypted; run `alembic upgrade head`.")
        return value
    try:
        return _cipher().decrypt(value[len(ENVELOPE) :].encode()).decode()
    except InvalidToken as exc:
        raise CredentialDecryptionError() from exc
