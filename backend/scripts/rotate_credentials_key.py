#!/usr/bin/env python
"""Re-encrypt stored provider credentials with the active key.

Rotation procedure:

1. Set `CREDENTIALS_ENCRYPTION_KEY="<new>,<old>"` — the first key encrypts, every key decrypts.
2. Restart the app so the new key set is loaded.
3. `python scripts/rotate_credentials_key.py --dry-run` — verifies every row opens with the new set.
4. `python scripts/rotate_credentials_key.py` — rewrites every row with the active key.
5. Remove `<old>` from the environment and restart.

The script is idempotent: running it twice changes nothing but the nonces.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.db.encryption import CREDENTIAL_COLUMNS, reencrypt_all  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-encrypt stored credentials with the active key.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify every row decrypts with the current key set, then exit without writing.",
    )
    args = parser.parse_args(argv)

    keys = get_settings().encryption_keys
    if not keys:
        raise SystemExit("CREDENTIALS_ENCRYPTION_KEY is not set; nothing can be re-encrypted.")
    print(f"active key set: {len(keys)} key(s)")

    db = SessionLocal()
    try:
        try:
            counts = reencrypt_all(db.connection(), dry_run=args.dry_run)
        except Exception as exc:
            db.rollback()
            raise SystemExit(f"Failed, nothing written: {exc}") from exc
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    width = max((len(table) for table, _ in CREDENTIAL_COLUMNS), default=5)
    verb = "would re-encrypt" if args.dry_run else "re-encrypted"
    for table, column in CREDENTIAL_COLUMNS:
        print(f"{table.ljust(width)}  {column:<8}  {verb} {counts.get(table, 0):>4}")
    print("dry run: nothing written" if args.dry_run else "rotation complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
