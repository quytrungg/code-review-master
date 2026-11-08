"""SQLAlchemy column type for stored secrets.

The plaintext never reaches the database and callers never see ciphertext: binds encrypt,
results decrypt, so `key.token` / `key.api_key` stay ordinary strings in services and routes.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Text, TypeDecorator
from sqlalchemy.engine import Dialect

from app.core.crypto import decrypt_secret, encrypt_secret


class EncryptedText(TypeDecorator):
    """Text whose stored form is authenticated ciphertext (see `app.core.crypto`)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        return None if value is None else encrypt_secret(str(value))

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:
        return None if value is None else decrypt_secret(str(value))
