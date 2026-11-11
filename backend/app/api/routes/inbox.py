"""The PR inbox: sync the GitHub review queue, list the cache, post a quick review.

Routes stay thin: validation here, the GitHub calls in `github_inbox_service`. `KeyError` is the
one exception the service raises, so the mapping lives in a single helper.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_db
from app.schemas.inbox import (
    CachedPRRead,
    InboxSyncResponse,
    PolishRequest,
    PolishResponse,
    QuickReviewRequest,
)
from app.services import github_inbox_service
from app.services.keys_service import KeyError

router = APIRouter(prefix="/inbox", tags=["inbox"])


def _map(exc: KeyError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("", response_model=list[CachedPRRead])
def list_inbox(
    user: CurrentUser,
    status: str | None = None,
    repo: str | None = None,
    unread: bool = False,
    db: Session = Depends(get_db),
) -> list[CachedPRRead]:
    try:
        rows = github_inbox_service.list_inbox(
            db, user.id, status=status, repo=repo, unread=unread
        )
    except KeyError as exc:
        raise _map(exc) from exc
    return [CachedPRRead.from_row(row) for row in rows]


@router.post("/sync", response_model=InboxSyncResponse)
async def sync_inbox(user: CurrentUser, db: Session = Depends(get_db)) -> InboxSyncResponse:
    """Re-read the GitHub review queue for this account and rebuild the local cache."""
    try:
        rows, gone, warnings = await github_inbox_service.sync_inbox(db, user.id)
    except KeyError as exc:
        raise _map(exc) from exc
    return InboxSyncResponse(
        items=[CachedPRRead.from_row(row) for row in rows], disappeared=gone, warnings=warnings
    )


@router.post("/quick-review", response_model=CachedPRRead)
async def quick_review(
    payload: QuickReviewRequest, user: CurrentUser, db: Session = Depends(get_db)
) -> CachedPRRead:
    """Dispatch one top-level review to GitHub and mark the inbox item accordingly."""
    try:
        row = await github_inbox_service.quick_review(
            db, user.id, payload.cached_pr_id, payload.event, payload.body
        )
    except KeyError as exc:
        raise _map(exc) from exc
    return CachedPRRead.from_row(row)


@router.post("/polish", response_model=PolishResponse)
async def polish(
    payload: PolishRequest, user: CurrentUser, db: Session = Depends(get_db)
) -> PolishResponse:
    """Rewrite a quick-review draft with the account's active model; prose, no ledger of content."""
    try:
        return PolishResponse(text=await github_inbox_service.polish(db, user.id, payload.text))
    except KeyError as exc:
        raise _map(exc) from exc
