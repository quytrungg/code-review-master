from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


def utcnow() -> datetime:
    """Timezone-aware UTC now, stored consistently for PostgreSQL compatibility."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass
