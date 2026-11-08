"""Database-backed progress bus for review ingestion.

A review's stages are stored in `review_events` instead of process memory, because the ingest job
and the browser's SSE stream can be served by different instances (and a cold start forgets
everything). `publish` owns a short session: progress is best-effort and must survive the caller's
rollback — the terminal event of a crashed ingest is published *after* `db.rollback()`.

Retention matches the old in-memory behaviour: the newest `MAX_EVENTS_PER_REVIEW` rows per review.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.db.base import utcnow
from app.db.session import SessionLocal
from app.models.review import ReviewEvent

logger = logging.getLogger(__name__)

MAX_EVENTS_PER_REVIEW = 200
POLL_SECONDS = 0.5
HEARTBEAT_SECONDS = 15.0

INFO = "info"
WARN = "warn"
ERROR = "error"


@dataclass
class ProgressEvent:
    seq: int
    ts: str
    stage: str
    label: str
    detail: str | None = None
    level: str = INFO
    progress: int | None = None
    data: dict[str, Any] | None = None
    terminal: bool = False

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("terminal", None)
        return payload

    @classmethod
    def from_row(cls, row: ReviewEvent) -> "ProgressEvent":
        return cls(
            seq=row.seq,
            ts=_iso(row.ts),
            stage=row.stage,
            label=row.label,
            detail=row.detail,
            level=row.level,
            progress=row.progress,
            data=row.data,
            terminal=row.terminal,
        )


def _iso(value: datetime) -> str:
    """UTC ISO-8601 with a `Z` suffix, whatever the driver returned (SQLite drops the zone)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _next_seq(db, review_id: int) -> int:
    current = db.scalar(
        select(func.coalesce(func.max(ReviewEvent.seq), 0)).where(
            ReviewEvent.review_id == review_id
        )
    )
    return int(current or 0) + 1


class ProgressBus:
    def publish(
        self,
        review_id: int,
        stage: str,
        label: str,
        *,
        detail: str | None = None,
        level: str = INFO,
        progress: int | None = None,
        data: dict[str, Any] | None = None,
        terminal: bool = False,
    ) -> ProgressEvent | None:
        """Append one event. Returns `None` (and logs) when it could not be stored.

        Progress is diagnostics, never a reason for an ingest or a request to fail. A concurrent
        writer can take the same `seq`; the unique constraint turns that into one retry.
        """
        for _ in range(2):
            with SessionLocal() as db:
                try:
                    seq = _next_seq(db, review_id)
                    row = ReviewEvent(
                        review_id=review_id,
                        seq=seq,
                        ts=utcnow(),
                        stage=stage,
                        label=label,
                        detail=detail,
                        level=level,
                        progress=progress,
                        data=data,
                        terminal=terminal,
                    )
                    db.add(row)
                    if seq > MAX_EVENTS_PER_REVIEW:
                        db.execute(
                            delete(ReviewEvent).where(
                                ReviewEvent.review_id == review_id,
                                ReviewEvent.seq <= seq - MAX_EVENTS_PER_REVIEW,
                            )
                        )
                    db.commit()
                    return ProgressEvent.from_row(row)
                except IntegrityError:
                    db.rollback()
                    continue
                except SQLAlchemyError:
                    db.rollback()
                    logger.exception("Could not store progress event %s for review %s", stage, review_id)
                    return None
        logger.warning("Gave up storing progress event %s for review %s", stage, review_id)
        return None

    def history(self, review_id: int, after_seq: int = 0) -> list[ProgressEvent]:
        with SessionLocal() as db:
            rows = db.scalars(
                select(ReviewEvent)
                .where(ReviewEvent.review_id == review_id, ReviewEvent.seq > after_seq)
                .order_by(ReviewEvent.seq)
            ).all()
            return [ProgressEvent.from_row(row) for row in rows]

    def is_finished(self, review_id: int) -> bool:
        with SessionLocal() as db:
            row = db.scalars(
                select(ReviewEvent.id).where(
                    ReviewEvent.review_id == review_id, ReviewEvent.terminal.is_(True)
                )
            ).first()
            return row is not None

    def reset(self) -> None:
        """Drop every stored event; tests use it between cases."""
        with SessionLocal() as db:
            db.execute(delete(ReviewEvent))
            db.commit()

    async def subscribe(self, review_id: int) -> AsyncIterator[ProgressEvent | None]:
        """Replay history, then poll for new rows; `None` means "send a keep-alive"."""
        last = 0
        idle = 0.0
        while True:
            events = await asyncio.to_thread(self.history, review_id, last)
            if events:
                idle = 0.0
                for event in events:
                    last = event.seq
                    yield event
                    if event.terminal:
                        return
                continue
            await asyncio.sleep(POLL_SECONDS)
            idle += POLL_SECONDS
            if idle >= HEARTBEAT_SECONDS:
                idle = 0.0
                yield None


bus = ProgressBus()
