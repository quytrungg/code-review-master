"""Cross-review finding search and "seen before". Read-only; every query is owner-scoped."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_db
from app.models.review import CodeReview, ReviewThread
from app.schemas.findings import FindingHitRead, FindingSearchResponse, SimilarFindingsResponse
from app.services import finding_search

router = APIRouter(prefix="/findings", tags=["findings"])


@router.get("/search", response_model=FindingSearchResponse)
def search_findings(
    user: CurrentUser,
    q: str | None = Query(default=None, max_length=200),
    repo: str | None = Query(default=None, max_length=200),
    path: str | None = Query(default=None, max_length=400),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> FindingSearchResponse:
    """Findings across this account's reviews by words, repository, path or date.

    An empty request is a `422` rather than a scan of the whole corpus: the dashboard's search box
    always sends at least one term, and an unbounded query is not a search.
    """
    if not any((q, repo, path, since)):
        raise HTTPException(
            status_code=422, detail="Add a search term, a repository, a path or a date."
        )
    hits, total = finding_search.search(
        db, user.id, query=q, repo=repo, path=path, since=since, limit=limit
    )
    return FindingSearchResponse(
        items=[FindingHitRead.from_hit(hit) for hit in hits], total=total
    )


@router.get(
    "/similar/{review_id}/{thread_id}", response_model=SimilarFindingsResponse
)
def similar_findings(
    review_id: int,
    thread_id: int,
    user: CurrentUser,
    limit: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> SimilarFindingsResponse:
    """Prior findings in the same repository with the same normalised key.

    Ownership first: another account's review or thread is a `404`, never a `403`.
    """
    review = db.scalars(
        select(CodeReview).where(CodeReview.id == review_id, CodeReview.user_id == user.id)
    ).first()
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    thread = db.scalars(
        select(ReviewThread).where(
            ReviewThread.id == thread_id, ReviewThread.review_id == review.id
        )
    ).first()
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    hits = finding_search.similar(db, user.id, review, thread, limit=limit)
    return SimilarFindingsResponse(items=[FindingHitRead.from_hit(hit) for hit in hits])
