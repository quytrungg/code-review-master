from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core.config import BACKEND_DIR
from app.db.session import engine

logger = logging.getLogger(__name__)

ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


def upgrade_to_head() -> None:
    command.upgrade(alembic_config(), "head")


def init_db() -> None:
    """Bring the local database up to the latest revision on startup.

    Alembic stays the single source of truth for schema; running the upgrade
    programmatically only removes the manual first-run step for a local app.
    """
    if not Path(ALEMBIC_INI).is_file():
        logger.warning("alembic.ini not found at %s; skipping migrations", ALEMBIC_INI)
        return

    if not inspect(engine).has_table("alembic_version"):
        logger.info("No schema found, running alembic upgrade head")
    upgrade_to_head()


def fail_orphaned_reviews() -> int:
    """Mark reviews left `running` by a previous process as failed.

    Used by local and container runs, where one long-lived process owns every job: anything still
    `running` at startup belonged to a process that no longer exists. Serverless deployments must
    not call this — another instance may own that review — and use
    `mark_stale_running_reviews()` on read instead.
    """
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.review import CodeReview, ReviewStatus

    db = SessionLocal()
    try:
        rows = db.scalars(
            select(CodeReview).where(CodeReview.status == ReviewStatus.RUNNING)
        ).all()
        for row in rows:
            row.status = ReviewStatus.FAILED
            row.error = "Interrupted by a server restart before the review finished."
        if rows:
            db.commit()
            logger.info("Marked %s interrupted review(s) as failed", len(rows))
        return len(rows)
    finally:
        db.close()


STALE_RUNNING_SECONDS = 600


def mark_stale_running_reviews(max_age_seconds: int = STALE_RUNNING_SECONDS) -> int:
    """Fail `running` reviews whose last database write is older than an invocation can live.

    A serverless function is killed at its maximum duration, leaving a row no process will ever
    finish. A review younger than the threshold may still be running in another instance, so it is
    left alone. Read paths call this; startup must not, for exactly that reason.
    """
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.review import CodeReview, ReviewStatus
    from app.services.progress import ERROR, bus

    cutoff = datetime.now(timezone.utc).timestamp() - max_age_seconds
    flipped: list[tuple[int, str]] = []
    db = SessionLocal()
    try:
        rows = db.scalars(
            select(CodeReview).where(CodeReview.status == ReviewStatus.RUNNING)
        ).all()
        for row in rows:
            stamp = row.updated_at
            if stamp.tzinfo is None:
                # SQLite stores naive UTC; PostgreSQL may hand back an aware value.
                stamp = stamp.replace(tzinfo=timezone.utc)
            if stamp.timestamp() > cutoff:
                continue
            detail = "Interrupted: the server stopped before this review finished. Create it again."
            row.status = ReviewStatus.FAILED
            row.error = detail
            flipped.append((row.id, detail))
        if flipped:
            db.commit()
    finally:
        db.close()

    for review_id, detail in flipped:
        bus.publish(review_id, "error", "Review failed", detail=detail, level=ERROR, terminal=True)
    if flipped:
        logger.info("Marked %s stale running review(s) as failed", len(flipped))
    return len(flipped)
