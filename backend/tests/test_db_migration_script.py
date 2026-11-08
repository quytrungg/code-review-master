from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

import migrate_sqlite_to_postgres as mig  # noqa: E402


def test_relative_sqlite_source_resolves_against_backend() -> None:
    assert mig._resolve_url("sqlite:///./app.db") == f"sqlite:///{BACKEND_DIR / 'app.db'}"


def test_absolute_and_server_urls_are_left_alone() -> None:
    assert mig._resolve_url("sqlite:////tmp/legacy.db") == "sqlite:////tmp/legacy.db"
    assert mig._resolve_url("postgresql+psycopg://localhost/code_review") == (
        "postgresql+psycopg://localhost/code_review"
    )


def test_naive_sqlite_timestamps_are_reattached_as_utc() -> None:
    metadata = sa.MetaData()
    tz_table = sa.Table("t", metadata, sa.Column("id", sa.Integer), sa.Column(
        "created_at", sa.DateTime(timezone=True)
    ))
    plain_table = sa.Table("p", metadata, sa.Column("id", sa.Integer), sa.Column(
        "created_at", sa.DateTime()
    ))
    naive = datetime(2026, 11, 7, 10, 30)

    converted = mig._coerce({"id": 1, "created_at": naive}, tz_table)
    assert converted["created_at"].tzinfo is timezone.utc
    assert converted["created_at"].replace(tzinfo=None) == naive

    # A non-tz column keeps the wall time it was stored with.
    untouched = mig._coerce({"id": 1, "created_at": naive}, plain_table)
    assert untouched["created_at"].tzinfo is None


def test_copy_into_sqlite_target_is_refused() -> None:
    with pytest.raises(SystemExit, match="Target must be PostgreSQL"):
        mig.migrate("sqlite:////tmp/a.db", "sqlite:////tmp/b.db", truncate=False, dry_run=True)


def test_same_source_and_target_is_refused() -> None:
    url = "postgresql+psycopg://localhost/code_review"
    with pytest.raises(SystemExit, match="same database"):
        mig.migrate(url, url, truncate=False, dry_run=True)
