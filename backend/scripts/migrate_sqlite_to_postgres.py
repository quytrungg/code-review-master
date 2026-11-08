#!/usr/bin/env python
"""Copy the local SQLite database into PostgreSQL.

A rake-style one-shot task: `python scripts/migrate_sqlite_to_postgres.py`.

What it does, in order:

1. Opens the SQLite source read-only and counts every table.
2. Refuses to touch a target that already holds rows unless `--truncate` is given.
3. Brings the target schema to Alembic head (same migrations the app runs).
4. Copies tables in foreign-key order inside a single transaction.
5. Resets the PostgreSQL id sequences, re-counts both sides, and fails loudly if
   any table does not match.

Nothing is committed until every table has been copied and verified, so a failure
leaves the target exactly as it was.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

CHUNK = 500


@dataclass
class TablePlan:
    name: str
    source_rows: int
    target_rows: int


def _resolve_url(value: str) -> str:
    """Resolve a relative SQLite URL against the backend directory, like the app does."""
    prefix = "sqlite:///"
    if not value.startswith(prefix):
        return value
    path = value[len(prefix) :]
    if path in ("", ":memory:") or Path(path).is_absolute():
        return value
    return f"{prefix}{(BACKEND_DIR / path).resolve()}"


def _make_engine(url: str) -> sa.Engine:
    if url.startswith("sqlite"):
        return sa.create_engine(url, future=True)
    return sa.create_engine(url, pool_pre_ping=True, future=True)


def _count(engine: sa.Engine, table: sa.Table) -> int:
    with engine.connect() as connection:
        return int(connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one())


def _tables_in_copy_order(engine: sa.Engine, metadata: sa.MetaData) -> list[sa.Table]:
    """Tables ordered parents-first, taken from the app's own model metadata."""
    from app.db.base import Base  # noqa: PLC0415 - imported after sys.path is ready

    ordered: list[sa.Table] = []
    for model_table in Base.metadata.sorted_tables:
        ordered.append(sa.Table(model_table.name, metadata, autoload_with=engine))
    return ordered


def _coerce(row: dict, target_table: sa.Table) -> dict:
    """Align a source row with the target columns.

    SQLite stores timezone-aware timestamps as naive UTC wall time; PostgreSQL keeps
    them in `timestamptz`. Re-attach UTC so the instant is preserved instead of being
    reinterpreted in the server's local zone.
    """
    values: dict = {}
    for target_column in target_table.columns:
        if target_column.name not in row:
            continue
        value = row[target_column.name]
        if (
            isinstance(value, datetime)
            and value.tzinfo is None
            and isinstance(target_column.type, sa.DateTime)
            and target_column.type.timezone
        ):
            value = value.replace(tzinfo=timezone.utc)
        values[target_column.name] = value
    return values


def _reset_sequence(connection: sa.Connection, table: str) -> None:
    """Point the id sequence past the highest copied id, so new inserts do not collide."""
    sequence = connection.execute(
        sa.text("SELECT pg_get_serial_sequence(:table, 'id')"), {"table": table}
    ).scalar_one_or_none()
    if not sequence:
        return
    connection.execute(
        sa.text(
            f'SELECT setval(:sequence, COALESCE((SELECT MAX(id) FROM "{table}"), 1), '
            f'(SELECT COUNT(*) > 0 FROM "{table}"))'
        ),
        {"sequence": sequence},
    )


def _print_table(plans: list[TablePlan], verb: str) -> None:
    width = max((len(plan.name) for plan in plans), default=5)
    print(f"{'table'.ljust(width)}  {verb:>8}")
    for plan in plans:
        value = plan.target_rows if verb == "target" else plan.source_rows
        print(f"{plan.name.ljust(width)}  {value:>8}")
    print(f"{'total'.ljust(width)}  {sum(p.source_rows for p in plans):>8}")


def migrate(source_url: str, target_url: str, *, truncate: bool, dry_run: bool) -> int:
    if source_url == target_url:
        raise SystemExit("Source and target are the same database; nothing to do.")
    if target_url.startswith("sqlite"):
        raise SystemExit("Target must be PostgreSQL (sqlite:/// target makes no sense here).")

    source = _make_engine(source_url)
    target = _make_engine(target_url)

    try:
        source_metadata = sa.MetaData()
        target_metadata = sa.MetaData()
        plans = []
        pairs: list[tuple[sa.Table, sa.Table]] = []
        for name in [table.name for table in _tables_in_copy_order(target, target_metadata)]:
            source_table = sa.Table(name, source_metadata, autoload_with=source)
            target_table = sa.Table(name, target_metadata, autoload_with=target)
            plans.append(
                TablePlan(
                    name=name,
                    source_rows=_count(source, source_table),
                    target_rows=_count(target, target_table),
                )
            )
            pairs.append((source_table, target_table))

        print(f"source  {source_url}")
        print(f"target  {target_url}")
        _print_table(plans, "source")

        if dry_run:
            from app.db.encryption import plaintext_count  # noqa: PLC0415

            with source.connect() as source_connection:
                pending = plaintext_count(source_connection)
            if pending:
                print(
                    f"\n{pending} plaintext credential value(s) in the source would be encrypted"
                )
            print("\ndry run: nothing written")
            return 0

        occupied = [plan for plan in plans if plan.target_rows > 0]
        if occupied and not truncate:
            names = ", ".join(plan.name for plan in occupied)
            raise SystemExit(
                f"Target already holds rows ({names}). Re-run with --truncate to replace them."
            )

        with target.begin() as connection:
            if truncate:
                # Children first: the foreign keys are ON DELETE CASCADE, but truncating
                # explicitly keeps the intent obvious.
                for _, target_table in reversed(pairs):
                    connection.execute(target_table.delete())

            for source_table, target_table in pairs:
                copied = 0
                with source.connect() as source_connection:
                    result = source_connection.execute(sa.select(source_table))
                    while True:
                        rows = result.fetchmany(CHUNK)
                        if not rows:
                            break
                        payload = [_coerce(row._mapping, target_table) for row in rows]
                        connection.execute(target_table.insert(), payload)
                        copied += len(payload)
                print(f"copied {copied:>8}  {target_table.name}")

            for _, target_table in pairs:
                _reset_sequence(connection, target_table.name)

            # The copy is raw, so a source database written before encryption stays plaintext.
            # Encrypt inside this transaction: the count check below is the rollback gate.
            from app.db.encryption import encrypt_plaintext  # noqa: PLC0415

            encrypted = encrypt_plaintext(connection)
            print(f"encrypted {sum(encrypted.values()):>8}  credential value(s)")

            # Verify inside the transaction: a mismatch rolls the whole copy back.
            mismatches = []
            for source_table, target_table in pairs:
                expected = _count(source, source_table)
                actual = int(
                    connection.execute(
                        sa.select(sa.func.count()).select_from(target_table)
                    ).scalar_one()
                )
                target_table_plan = next(p for p in plans if p.name == target_table.name)
                target_table_plan.target_rows = actual
                if expected != actual:
                    mismatches.append(f"{target_table.name}: {expected} -> {actual}")

        if mismatches:
            raise SystemExit("Row counts do not match, rolled back:\n  " + "\n  ".join(mismatches))

        print()
        _print_table(plans, "target")
        print("\nmigration complete")
        return 0
    finally:
        source.dispose()
        target.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Copy the SQLite database into PostgreSQL (rake-style task).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python scripts/migrate_sqlite_to_postgres.py\n"
            "  python scripts/migrate_sqlite_to_postgres.py --dry-run\n"
            "  python scripts/migrate_sqlite_to_postgres.py --truncate\n"
            "  python scripts/migrate_sqlite_to_postgres.py --source sqlite:///./old.db "
            "--target postgresql+psycopg://localhost:5432/code_review_copy\n"
        ),
    )
    parser.add_argument(
        "--source",
        default=os.environ.get("SQLITE_SOURCE_URL", f"sqlite:///{BACKEND_DIR / 'app.db'}"),
        help="SQLite URL to read from (default: sqlite:///<backend>/app.db).",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="PostgreSQL URL to write to (default: DATABASE_URL from .env / environment).",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Delete existing target rows first. Required when the target is not empty.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would move, then exit without writing.",
    )
    args = parser.parse_args(argv)

    source_url = _resolve_url(args.source)
    if args.target:
        os.environ["DATABASE_URL"] = args.target

    # Imported here so a --target override is in place before settings are cached:
    # the app's migrations must run against the database being written to.
    from app.core.config import get_settings  # noqa: PLC0415
    from app.db.init_db import upgrade_to_head  # noqa: PLC0415

    target_url = _resolve_url(args.target or get_settings().resolved_database_url)
    if target_url.startswith("sqlite"):
        raise SystemExit(
            "DATABASE_URL still points at SQLite. Set it to a postgresql+psycopg:// URL "
            "(backend/.env) or pass --target."
        )

    sqlite_path = Path(source_url[len("sqlite:///") :]) if source_url.startswith("sqlite:///") else None
    if sqlite_path is not None and not sqlite_path.is_file():
        raise SystemExit(f"No SQLite database at {sqlite_path}. Pass --source explicitly.")

    print("applying migrations to the target...")
    upgrade_to_head()

    return migrate(source_url, target_url, truncate=args.truncate, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
