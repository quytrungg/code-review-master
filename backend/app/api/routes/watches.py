"""Watches: list, create from a review, pause, delete, and the cron tick.

Two routers on purpose. `router` is the owner-scoped CRUD surface and is mounted behind the session
dependency like every other account route. `tick_router` is the one public endpoint in the product
besides `/api/auth/*`: a cron job cannot hold a session cookie, so it authenticates with a shared
secret instead (`WATCH_TICK_SECRET`), and it answers `503` when that secret is not configured —
failing closed is the only safe default for an endpoint that starts model calls.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_db
from app.core.config import get_settings
from app.models.review import CodeReview
from app.schemas.watch import (
    CreateWatchRequest,
    ReviewWatchRead,
    TickResultRead,
    UpdateWatchRequest,
    WatchCheckRead,
)
from app.services import watch_service
from app.services.review_pipeline import schedule_ingest

router = APIRouter(prefix="/watches", tags=["watches"])
tick_router = APIRouter(prefix="/watches", tags=["watches"])


@router.get("", response_model=list[ReviewWatchRead])
def list_watches(user: CurrentUser, db: Session = Depends(get_db)) -> list[ReviewWatchRead]:
    return [ReviewWatchRead.from_row(row) for row in watch_service.list_watches(db, user.id)]


@router.post("", response_model=ReviewWatchRead, status_code=201)
def create_watch(
    payload: CreateWatchRequest,
    response: Response,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> ReviewWatchRead:
    """Watch the PR this review covers. Idempotent: the same PR returns the existing watch, `200`."""
    review = db.scalars(
        select(CodeReview).where(
            CodeReview.id == payload.review_id, CodeReview.user_id == user.id
        )
    ).first()
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")

    watch, created = watch_service.create_watch(db, user.id, review)
    if not created:
        response.status_code = 200
    return ReviewWatchRead.from_row(watch)


@router.patch("/{watch_id}", response_model=ReviewWatchRead)
def update_watch(
    watch_id: int,
    payload: UpdateWatchRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> ReviewWatchRead:
    watch = watch_service.owned_watch(db, user.id, watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="Watch not found")
    return ReviewWatchRead.from_row(watch_service.set_enabled(db, watch, payload.enabled))


@router.delete("/{watch_id}", status_code=204)
def delete_watch(watch_id: int, user: CurrentUser, db: Session = Depends(get_db)) -> Response:
    watch = watch_service.owned_watch(db, user.id, watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="Watch not found")
    watch_service.delete_watch(db, watch)
    return Response(status_code=204)


@router.post("/{watch_id}/check", status_code=202, response_model=WatchCheckRead)
async def check_watch(
    watch_id: int,
    response: Response,
    user: CurrentUser,
    background: BackgroundTasks,
) -> WatchCheckRead:
    """Check this watch now instead of waiting for the next tick.

    `202` when a delta review started (its progress streams from `/api/reviews/{id}/events`), `200`
    when there is nothing to review, `404` for another account's watch, `502` when the head could
    not be read. Works on a paused watch: `enabled` gates the poll, not the click.
    """
    outcome = await watch_service.check_now(user.id, watch_id)
    if outcome is None:
        raise HTTPException(status_code=404, detail="Watch not found")
    if outcome.status == "failed":
        raise HTTPException(
            status_code=502, detail=outcome.detail or "The change request could not be read."
        )

    claim = outcome.claim
    if claim is not None:
        schedule_ingest(claim.review_id, background, pr=claim.pr, diff_text=claim.diff_text)
        return WatchCheckRead(
            status=outcome.status, review_id=claim.review_id, head_sha=outcome.head_sha
        )

    response.status_code = 200
    return WatchCheckRead(status=outcome.status, head_sha=outcome.head_sha, detail=outcome.detail)


def require_tick_secret(request: Request) -> None:
    """Shared-secret gate for the cron tick. Never compares a missing secret."""
    expected = (get_settings().watch_tick_secret or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Watch ticks are not configured: set WATCH_TICK_SECRET to enable them.",
        )

    provided = (request.headers.get("x-watch-secret") or "").strip()
    if not provided:
        authorization = (request.headers.get("authorization") or "").strip()
        if authorization.lower().startswith("bearer "):
            provided = authorization[7:].strip()

    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid watch tick secret.",
            headers={"WWW-Authenticate": "Bearer"},
        )


@tick_router.post("/tick", response_model=TickResultRead, dependencies=[Depends(require_tick_secret)])
async def run_tick() -> TickResultRead:
    """Check every enabled watch once. Idempotent: an unchanged head starts nothing."""
    outcome = await watch_service.tick()
    return TickResultRead(**outcome.as_dict())
