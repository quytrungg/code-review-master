"""Watching a change request: one tick checks every watch and starts a delta review when the head moves.

A tick has exactly one hard problem — two ticks must never produce two reviews for one commit — so
the claim is a single compare-and-set `UPDATE … WHERE last_seen_commit_id = <old>` issued in the same
transaction as the review insert. That is atomic on PostgreSQL and SQLite alike (no `SELECT … FOR
UPDATE`, which SQLite ignores), no lock is held across the network call, and a failed creation rolls
the claim back so the next tick retries. `UNIQUE(watch_id, commit_id)` on `code_reviews` is the
second guard, for the case where the claim logic is ever wrong.

`last_seen_commit_id` advances when the review is *created*, not when it succeeds: a failed delta
review stays visible as `failed`, the watch keeps moving with later pushes, and the operator can
re-run that pull request by hand. Advancing on success would re-review the same delta on every tick
until the model cooperated — the review spam this feature exists to avoid.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import utcnow
from app.db.session import SessionLocal
from app.models.review import CodeReview
from app.models.watch import ReviewTrigger, ReviewWatch
from app.services import keys_service, vcs
from app.services.review_pipeline import PipelineError, create_running_review, run_ingest

logger = logging.getLogger(__name__)

MAX_ERROR_CHARS = 200

# One loop per process; `start_loop` is idempotent. `_loop_owner` is the event loop that created
# the task — a task can only be awaited from its own loop.
_loop_task: asyncio.Task | None = None
_loop_owner: asyncio.AbstractEventLoop | None = None


@dataclass
class TickResult:
    """What one tick did. `failed` names the watch and the first line of the cause."""

    checked: int = 0
    unchanged: int = 0
    adopted: int = 0
    skipped: int = 0
    started: list[int] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "checked": self.checked,
            "unchanged": self.unchanged,
            "adopted": self.adopted,
            "skipped": self.skipped,
            "started": list(self.started),
            "failed": list(self.failed),
        }


def create_watch(db: Session, user_id: int, review: CodeReview) -> tuple[ReviewWatch, bool]:
    """Watch `review`'s pull request. Returns `(watch, created)`; one watch per PR per account."""
    existing = db.scalars(
        select(ReviewWatch).where(
            ReviewWatch.user_id == user_id, ReviewWatch.pr_url == review.pr_url
        )
    ).first()
    if existing is not None:
        # Pressing "watch" on a paused watch is a resume, not a second watch.
        if not existing.enabled:
            existing.enabled = True
            db.commit()
            db.refresh(existing)
        return existing, False

    watch = ReviewWatch(
        user_id=user_id,
        pr_url=review.pr_url,
        vcs=review.vcs or "github",
        repo_full_name=review.repo_full_name,
        pr_number=review.pr_number,
        skill_foundation=review.skill_foundation,
        model_used=review.model_used,
        # The delta base is the head this review already covered; NULL means "adopt on first check".
        last_seen_commit_id=review.commit_id,
        last_review_id=review.id,
        enabled=True,
    )
    db.add(watch)
    db.commit()
    db.refresh(watch)
    return watch, True


def list_watches(db: Session, user_id: int) -> list[ReviewWatch]:
    return list(
        db.scalars(
            select(ReviewWatch)
            .where(ReviewWatch.user_id == user_id)
            .order_by(ReviewWatch.created_at.desc(), ReviewWatch.id.desc())
        )
    )


def owned_watch(db: Session, user_id: int, watch_id: int) -> ReviewWatch | None:
    """Another account's watch is `None` -> the route answers 404, never 403."""
    return db.scalars(
        select(ReviewWatch).where(ReviewWatch.id == watch_id, ReviewWatch.user_id == user_id)
    ).first()


def watch_for(db: Session, user_id: int, pr_url: str) -> ReviewWatch | None:
    """The watch covering a review's pull request, for the workspace toggle."""
    return db.scalars(
        select(ReviewWatch).where(
            ReviewWatch.user_id == user_id, ReviewWatch.pr_url == pr_url
        )
    ).first()


def set_enabled(db: Session, watch: ReviewWatch, enabled: bool) -> ReviewWatch:
    watch.enabled = enabled
    db.commit()
    db.refresh(watch)
    return watch


def delete_watch(db: Session, watch: ReviewWatch) -> None:
    db.delete(watch)
    db.commit()


async def tick(max_reviews: int | None = None) -> TickResult:
    """Check enabled watches once, oldest check first, and start a delta review per moved head."""
    config = get_settings()
    budget = config.watch_max_reviews_per_tick if max_reviews is None else max_reviews
    result = TickResult()

    watch_ids = _due_watch_ids(config.watch_max_checks_per_tick)
    for index, watch_id in enumerate(watch_ids):
        if len(result.started) >= budget:
            # Out of review budget: leave the rest for the next tick rather than skipping them
            # permanently — the ordering is by `last_checked_at`, so the queue stays fair.
            result.skipped += len(watch_ids) - index
            break
        result.checked += 1
        try:
            status, review_id, error = await _check_watch(watch_id)
        except Exception as exc:  # noqa: BLE001 - one broken watch must not stop the tick
            logger.exception("Watch %s could not be checked", watch_id)
            result.failed.append({"watch_id": watch_id, "error": type(exc).__name__})
            continue
        if status == "started" and review_id is not None:
            result.started.append(review_id)
        elif status == "unchanged":
            result.unchanged += 1
        elif status == "adopted":
            result.adopted += 1
        elif status == "failed":
            result.failed.append({"watch_id": watch_id, "error": error})
        else:
            result.skipped += 1
    return result


async def _check_watch(watch_id: int) -> tuple[str, int | None, str | None]:
    """One watch: fetch the head, then no-op, adopt, or claim a delta and start its review."""
    with SessionLocal() as db:
        watch = db.get(ReviewWatch, watch_id)
        if watch is None or not watch.enabled:
            return "skipped", None, None

        try:
            ref = vcs.parse_pr_url(watch.pr_url)
            key = keys_service.version_control_for(db, watch.user_id, watch.vcs or ref.vcs)
            if key is None:
                raise vcs.VCSError(keys_service.missing_vcs_message(watch.vcs or ref.vcs), 400)
            pr = await vcs.fetch(key, ref)
        except vcs.VCSError as exc:
            _record_failure(db, watch, exc.message)
            return "failed", None, exc.message

        previous = watch.last_seen_commit_id
        if pr.head_sha == previous:
            _touch(db, watch)
            return "unchanged", None, None
        if not previous:
            # No base to compare against (a watch made from a review that never fetched): adopt
            # this head and review the *next* push, rather than reviewing the whole PR by accident.
            _touch(db, watch, last_seen=pr.head_sha)
            return "adopted", None, None

        try:
            claimed = db.execute(
                update(ReviewWatch)
                .where(
                    ReviewWatch.id == watch.id,
                    ReviewWatch.last_seen_commit_id == previous,
                )
                .values(last_seen_commit_id=pr.head_sha, last_checked_at=utcnow())
            ).rowcount
            if claimed != 1:
                db.rollback()
                return "skipped", None, None  # another tick owns this delta

            diff_text = await vcs.compare(key, ref, previous, pr.head_sha)
            review = create_running_review(
                db,
                watch.user_id,
                watch.pr_url,
                watch.model_used or "",
                watch.skill_foundation,
                commit_id=pr.head_sha,
                watch_id=watch.id,
                parent_review_id=watch.last_review_id,
                trigger=ReviewTrigger.WATCH,
            )
            # Read the id before the next commit expires the instance: ingest runs outside this
            # session, so a lazy refresh here would raise `DetachedInstanceError` later.
            review_id = review.id
            watch.last_review_id = review_id
            watch.last_error = None
            db.commit()
        except vcs.VCSError as exc:
            db.rollback()
            _record_failure(db, watch, exc.message)
            return "failed", None, exc.message
        except PipelineError as exc:
            db.rollback()
            _record_failure(db, watch, exc.detail)
            return "failed", None, exc.detail
        except IntegrityError:
            db.rollback()
            logger.info("Watch %s already has a review for %s", watch_id, pr.head_sha)
            # The review this delta would have produced already exists (another process got there
            # first). Roll the claim back would park the watch on the same commit forever, so move
            # it past the commit in its own transaction — retrying cannot help.
            _advance(db, watch, pr.head_sha)
            return "skipped", None, None

    # The review row is committed; ingest runs outside the session it was created in.
    await run_ingest(review_id, pr=pr, diff_text=diff_text)
    return "started", review_id, None


def _touch(db: Session, watch: ReviewWatch, *, last_seen: str | None = None) -> None:
    watch.last_checked_at = utcnow()
    watch.last_error = None
    if last_seen is not None:
        watch.last_seen_commit_id = last_seen
    db.commit()


def _advance(db: Session, watch: ReviewWatch, commit_id: str) -> None:
    """Move the watch past a commit without starting a review for it (the review already exists)."""
    try:
        watch.last_checked_at = utcnow()
        watch.last_seen_commit_id = commit_id
        watch.last_error = None
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.warning("Could not advance watch %s to %s", watch.id, commit_id)


def _record_failure(db: Session, watch: ReviewWatch, message: str | None) -> None:
    """Store the first line of a failure — never a prompt, a diff or a credential."""
    detail = " ".join((message or "").splitlines())[:MAX_ERROR_CHARS] or "Unknown error"
    try:
        watch.last_checked_at = utcnow()
        watch.last_error = detail
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.warning("Could not record the watch failure for %s", watch.id)


def _due_watch_ids(limit: int) -> list[int]:
    """Enabled watches, never-checked first, then oldest check. Both engines agree on this order."""
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(ReviewWatch.id)
                .where(ReviewWatch.enabled.is_(True))
                .order_by(
                    ReviewWatch.last_checked_at.is_(None).desc(),
                    ReviewWatch.last_checked_at.asc(),
                    ReviewWatch.id.asc(),
                )
                .limit(max(1, limit))
            )
        )


def start_loop() -> asyncio.Task | None:
    """Start the local watch loop. Serverless and `WATCH_INTERVAL_MINUTES=0` never start it."""
    global _loop_task, _loop_owner
    config = get_settings()
    if config.serverless:
        return None
    if config.watch_interval_minutes <= 0:
        logger.info("Watch loop disabled (WATCH_INTERVAL_MINUTES=%s)", config.watch_interval_minutes)
        return None

    try:
        current = asyncio.get_running_loop()
    except RuntimeError:  # no loop running: nothing to schedule onto
        return None
    if _loop_task is not None and not _loop_task.done() and _loop_owner is current:
        return _loop_task

    interval = config.watch_interval_minutes * 60
    # A task belongs to the loop that created it (a second app lifespan in one process — tests do
    # this — gets its own loop), so remember which one owns it.
    _loop_task = asyncio.create_task(_loop(interval))
    _loop_owner = current
    logger.info("Watch loop started: every %s minute(s)", config.watch_interval_minutes)
    return _loop_task


def stop_loop() -> asyncio.Task | None:
    """Cancel this loop's watch task; leave another loop's alone (a second app lifespan)."""
    global _loop_task, _loop_owner
    task, owner = _loop_task, _loop_owner
    if task is None or task.done():
        return None
    try:
        current = asyncio.get_running_loop()
    except RuntimeError:
        current = None
    if owner is not current:
        # Awaiting (or cancelling) a task from another loop raises; that loop owns its teardown.
        return None
    _loop_task, _loop_owner = None, None
    task.cancel()
    return task


def loop_task() -> asyncio.Task | None:
    return _loop_task


async def _loop(interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            outcome = await tick()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a broken tick must not kill the loop
            logger.exception("Watch tick failed")
            continue
        if outcome.started:
            logger.info(
                "Watch tick started %s review(s); %s unchanged, %s skipped",
                len(outcome.started),
                outcome.unchanged,
                outcome.skipped,
            )


__all__ = [
    "TickResult",
    "create_watch",
    "delete_watch",
    "list_watches",
    "loop_task",
    "owned_watch",
    "set_enabled",
    "start_loop",
    "stop_loop",
    "tick",
    "watch_for",
]
