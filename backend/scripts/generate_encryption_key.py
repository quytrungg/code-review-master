#!/usr/bin/env python
"""Print a Fernet key for `CREDENTIALS_ENCRYPTION_KEY`.

Paste it into `backend/.env` (gitignored) or the deployment's environment. Keep it out of the
database, out of the repository and out of database backups: without it the stored credentials
cannot be decrypted, and with it a stolen dump can be.

    cd backend && python scripts/generate_encryption_key.py
"""

from __future__ import annotations

import sys

from cryptography.fernet import Fernet


def main() -> int:
    key = Fernet.generate_key().decode()
    print(key)
    print(
        "\nAdd to backend/.env (never commit the real key):\n"
        f"CREDENTIALS_ENCRYPTION_KEY={key}\n\n"
        "Back the key up separately from the database: losing it means re-entering every stored "
        "credential.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
