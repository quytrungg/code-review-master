from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()

_url = _settings.resolved_database_url

_engine_kwargs: dict = {"pool_pre_ping": True, "future": True}
if _settings.serverless and not _url.startswith("sqlite"):
    # Serverless: one connection per invocation. Supabase's transaction pooler hands out a
    # different backend per statement, so psycopg's automatic prepared statements (it prepares
    # after five executions) would reference statements that do not exist on the next one.
    from sqlalchemy.pool import NullPool  # noqa: PLC0415 - only needed in this mode

    _engine_kwargs = {
        "poolclass": NullPool,
        "connect_args": {"prepare_threshold": None},
        "future": True,
    }
if _url.startswith("sqlite"):
    # SQLite disallows cross-thread sharing by default; FastAPI hands sessions to
    # worker threads, and a local file database is not a shared-cache concern here.
    _engine_kwargs = {"connect_args": {"check_same_thread": False}, "future": True}

engine = create_engine(_url, **_engine_kwargs)

if _url.startswith("sqlite"):
    # SQLite ignores ON DELETE CASCADE unless the pragma is enabled per connection.
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
