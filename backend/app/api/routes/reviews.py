from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_db
from app.db.init_db import mark_stale_running_reviews
from app.db.session import SessionLocal
from app.models.review import CodeReview
from app.schemas.comparison import (
    CompareRequest,
    ComparisonEstimate,
    ComparisonItem,
    ComparisonMatch,
    ComparisonRead,
    ComparisonSide,
)
from app.schemas.review import (
    ApplyRequest,
    ApplyResponse,
    CodeReviewDetail,
    CodeReviewSummary,
    CreateReviewAccepted,
    CreateReviewRequest,
    DiscussRequest,
    DiscussResponse,
    LessonApplyRequest,
    LessonApplyResponse,
    LessonDraftResponse,
    ReviewNotifications,
    RoundDecisionRequest,
    RoundDecisionResponse,
    SyncResponse,
    VerdictPushbackRead,
    VerdictPushbackRequest,
    VerdictPushbackResponse,
)
from app.schemas.watch import ReviewWatchRead
from app.services import (
    analytics,
    comparison,
    keys_service,
    lessons_service,
    review_notifications as review_notifications_service,
    settings_service,
    thread_sync,
    vcs,
    watch_service,
)
from app.services.apply_service import apply_review, decide_round
from app.services.discussion import discuss_threads, prepare_discussion, stream_discussion
from app.services.llm_service import LLMError
from app.services.progress import bus
from app.services.review_pipeline import PipelineError, create_running_review, schedule_ingest
from app.services.verdict import VerdictError, push_back
from app.services.skills_service import SkillError
from app.models.watch import ReviewTrigger

router = APIRouter(prefix="/reviews", tags=["reviews"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _detail(db: Session, review: CodeReview) -> CodeReviewDetail:
    """One review plus its call usage and its watch, so the header line is fresh after every action."""
    detail = CodeReviewDetail.from_row(review)
    detail.usage = analytics.review_usage(db, review.id)
    watch = watch_service.watch_for(db, review.user_id, review.pr_url)
    detail.watch = ReviewWatchRead.from_row(watch) if watch is not None else None
    return detail


def _owned_review(db: Session, user_id: int, review_id: int) -> CodeReview:
    """Another account's review is a 404, never a 403: ids must not be probe-able."""
    row = db.scalars(
        select(CodeReview).where(CodeReview.id == review_id, CodeReview.user_id == user_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return row


@router.get("/notifications", response_model=ReviewNotifications)
def review_notifications(user: CurrentUser, db: Session = Depends(get_db)) -> ReviewNotifications:
    """The Reviews badge: how many finished reviews the operator has not opened.

    Declared before `/{review_id}` so the literal segment is never parsed as an id.
    """
    mark_stale_running_reviews()
    return ReviewNotifications(unread_count=review_notifications_service.unread_count(db, user.id))


@router.get("", response_model=list[CodeReviewSummary])
def list_reviews(user: CurrentUser, db: Session = Depends(get_db)) -> list[CodeReviewSummary]:
    mark_stale_running_reviews()
    rows = db.scalars(
        select(CodeReview)
        .where(CodeReview.user_id == user.id)
        .order_by(CodeReview.created_at.desc(), CodeReview.id.desc())
    )
    return [CodeReviewSummary.from_row(row) for row in rows]


@router.post("", status_code=202, response_model=CreateReviewAccepted)
async def create_review(
    payload: CreateReviewRequest,
    user: CurrentUser,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Accept the review and return immediately; progress streams from /{id}/events."""
    try:
        review = create_running_review(
            db, user.id, payload.pr_url, payload.model, payload.skill_foundation
        )
    except PipelineError as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    schedule_ingest(review.id, background)
    return CreateReviewAccepted(
        id=review.id, status=review.status, skill_foundation=review.skill_foundation
    )


@router.get("/{review_id}/events")
async def review_events(review_id: int, user: CurrentUser) -> StreamingResponse:
    """Server-Sent Events: replayed history, then live progress until the job finishes."""
    mark_stale_running_reviews()
    with SessionLocal() as db:
        _owned_review(db, user.id, review_id)

    async def generator():
        yield "retry: 2000\n\n"
        async for event in bus.subscribe(review_id):
            if event is None:
                yield ": ping\n\n"
                continue
            name = (
                "done" if event.stage == "done" else "failed" if event.stage == "error" else "progress"
            )
            yield f"event: {name}\ndata: {json.dumps(event.to_payload())}\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/{review_id}", response_model=CodeReviewDetail)
def get_review(
    review_id: int, user: CurrentUser, db: Session = Depends(get_db)
) -> CodeReviewDetail:
    mark_stale_running_reviews()
    return _detail(db, _owned_review(db, user.id, review_id))


@router.post("/{review_id}/seen", response_model=CodeReviewSummary)
def mark_review_seen(
    review_id: int, user: CurrentUser, db: Session = Depends(get_db)
) -> CodeReviewSummary:
    """Acknowledge this review's finished state so it stops counting as a notification.

    Idempotent, and a `running` review is untouched: opening the workspace early must not swallow
    the notification the job will produce when it finishes.
    """
    review = review_notifications_service.mark_seen(db, _owned_review(db, user.id, review_id))
    return CodeReviewSummary.from_row(review)


@router.post("/{review_id}/discuss", response_model=DiscussResponse)
async def discuss_review(
    review_id: int,
    payload: DiscussRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> DiscussResponse:
    review = _owned_review(db, user.id, review_id)

    try:
        review, results, warnings, refreshed = await discuss_threads(db, review, payload.threads)
    except PipelineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return DiscussResponse(
        review=_detail(db, review),
        results=results,
        opinion_refreshed=refreshed,
        warnings=warnings,
    )


@router.post("/{review_id}/discuss/stream")
async def discuss_review_stream(
    review_id: int,
    payload: DiscussRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Discussion over SSE: per-thread events as answers are written.

    Validation errors are JSON before the stream opens; once it does, every thread ends in a
    `thread_done` or `thread_error` event and a terminal `done`, and each completed exchange
    is already persisted when its event is sent.
    """
    review = _owned_review(db, user.id, review_id)
    try:
        prepared = await prepare_discussion(db, review, payload.threads)
    except PipelineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    async def generator():
        async for event in stream_discussion(prepared):
            event = dict(event)
            name = event.pop("type")
            yield f"event: {name}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/{review_id}/apply", response_model=ApplyResponse)
async def apply_to_github(
    review_id: int,
    payload: ApplyRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> ApplyResponse:
    review = _owned_review(db, user.id, review_id)

    try:
        review, meta, warnings = await apply_review(db, review, payload)
    except PipelineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return ApplyResponse(
        review=_detail(db, review),
        github_review_url=meta["github_review_url"],
        comments_posted=meta["comments_posted"],
        replies_posted=meta.get("replies_posted", 0),
        summarised=meta["summarised"],
        dropped=meta["dropped"],
        warnings=warnings,
    )


@router.post("/{review_id}/sync", response_model=SyncResponse)
async def sync_review(
    review_id: int, user: CurrentUser, db: Session = Depends(get_db)
) -> SyncResponse:
    """Fetch the PR's comments again and append what this review has not seen."""
    review = _owned_review(db, user.id, review_id)
    try:
        ref = vcs.parse_pr_url(review.pr_url)
    except vcs.VCSError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    if not review.repo_full_name or not review.pr_number:
        raise HTTPException(status_code=422, detail="This review is not linked to a pull request.")

    key = keys_service.version_control_for(db, review.user_id, ref.vcs)
    if key is None:
        raise HTTPException(status_code=400, detail=keys_service.missing_vcs_message(ref.vcs))

    try:
        outcome = await thread_sync.sync_review(db, review, key, ref)
    except vcs.VCSError as exc:
        raise HTTPException(status_code=exc.status_code or 502, detail=exc.message) from exc

    return SyncResponse(
        review=_detail(db, review),
        new_threads=outcome.new_threads,
        new_rounds=outcome.new_rounds,
        warnings=outcome.warnings,
    )


@router.post("/{review_id}/rounds/{round_id}/decision", response_model=RoundDecisionResponse)
async def decide_round_state(
    review_id: int,
    round_id: int,
    payload: RoundDecisionRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> RoundDecisionResponse:
    review = _owned_review(db, user.id, review_id)
    try:
        review, warnings = await decide_round(
            db, review, round_id, payload.decision, payload.summary
        )
    except PipelineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return RoundDecisionResponse(review=_detail(db, review), warnings=warnings)


@router.post("/{review_id}/verdict/pushback", response_model=VerdictPushbackResponse)
async def push_back_verdict(
    review_id: int,
    payload: VerdictPushbackRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> VerdictPushbackResponse:
    """Put the reviewer's argument to the model; it either changes its opinion or holds it.

    Nothing is published here and the apply gate is untouched: an agreeing answer only rewrites the
    advisory `suggested_verdict`, which the reviewer still has to apply themselves.
    """
    review = _owned_review(db, user.id, review_id)
    try:
        row, review = await push_back(db, review, payload.argument)
    except VerdictError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return VerdictPushbackResponse(
        pushback=VerdictPushbackRead.from_row(row), review=_detail(db, review)
    )


@router.get("/{review_id}/verdict/pushbacks", response_model=list[VerdictPushbackRead])
def list_verdict_pushbacks(
    review_id: int, user: CurrentUser, db: Session = Depends(get_db)
) -> list[VerdictPushbackRead]:
    """Every push-back on this review, newest first, so the modal can show the exchange so far."""
    review = _owned_review(db, user.id, review_id)
    return [VerdictPushbackRead.from_row(row) for row in reversed(review.pushbacks)]


@router.post("/{review_id}/compare", status_code=202, response_model=CreateReviewAccepted)
async def compare_review(
    review_id: int,
    payload: CompareRequest,
    user: CurrentUser,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> CreateReviewAccepted:
    """Re-run the same pull request with a second model, linked to this review as its parent.

    The sibling is pinned to the primary's commit (`ReviewTrigger.COMPARISON` in the pipeline), so
    the two finding sets can be compared anchor-for-anchor. It is findings-only: the pipeline skips
    the PR-comment import, and apply refuses it.
    """
    review = _owned_review(db, user.id, review_id)
    if review.status == "running":
        raise HTTPException(
            status_code=409, detail="Wait for this review to finish before comparing models."
        )
    try:
        sibling = create_running_review(
            db,
            user.id,
            review.pr_url,
            payload.model,
            review.skill_foundation,
            commit_id=review.commit_id,
            parent_review_id=review.id,
            trigger=ReviewTrigger.COMPARISON,
        )
    except PipelineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    schedule_ingest(sibling.id, background)
    return CreateReviewAccepted(
        id=sibling.id, status=sibling.status, skill_foundation=sibling.skill_foundation
    )


def _comparison_pair(db: Session, user_id: int, review: CodeReview):
    pair = comparison.find_pair(db, user_id, review)
    if pair is None:
        raise HTTPException(status_code=404, detail="This review has no model comparison.")
    return pair


@router.get("/{review_id}/comparison", response_model=ComparisonRead)
def read_comparison(
    review_id: int, user: CurrentUser, db: Session = Depends(get_db)
) -> ComparisonRead:
    """The merge view for either side of a comparison; three buckets and provenance per item."""
    review = _owned_review(db, user.id, review_id)
    pair = _comparison_pair(db, user.id, review)
    merged = comparison.merge(pair.primary, pair.comparison)
    return ComparisonRead(
        primary=ComparisonSide(**merged["primary"]),
        comparison=ComparisonSide(**merged["comparison"]),
        both=[ComparisonMatch(**item) for item in merged["both"]],
        primary_only=[ComparisonItem(**item) for item in merged["primary_only"]],
        comparison_only=[ComparisonItem(**item) for item in merged["comparison_only"]],
        line_tolerance=merged["line_tolerance"],
    )


@router.get("/{review_id}/comparison/estimate", response_model=ComparisonEstimate)
def estimate_comparison(
    review_id: int,
    user: CurrentUser,
    model: str = Query(min_length=1, max_length=200),
    db: Session = Depends(get_db),
) -> ComparisonEstimate:
    """Cost of the second run, priced from the primary review's measured tokens."""
    review = _owned_review(db, user.id, review_id)
    source = review
    if review.trigger == ReviewTrigger.COMPARISON:
        source = _comparison_pair(db, user.id, review).primary
    try:
        estimate = comparison.estimate(db, source, model)
    except LLMError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ComparisonEstimate(**estimate)


def _lesson_thread(db: Session, user_id: int, review_id: int, thread_id: int):
    """Ownership first (a 404, never a 403), then the beta gate, then the thread."""
    review = _owned_review(db, user_id, review_id)
    if not settings_service.beta_enabled(db, user_id, lessons_service.LESSON_FLAG):
        raise HTTPException(
            status_code=422,
            detail="This beta feature is turned off. Enable it in Settings, under Beta features.",
        )
    try:
        return review, lessons_service.owned_thread(review, thread_id)
    except lessons_service.LessonError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/{review_id}/threads/{thread_id}/lesson/draft", response_model=LessonDraftResponse
)
async def draft_lesson(
    review_id: int,
    thread_id: int,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> LessonDraftResponse:
    """Draft a reusable rule from the finding — editable, applied only on the apply endpoint."""
    review, thread = _lesson_thread(db, user.id, review_id, thread_id)
    try:
        draft = await lessons_service.draft_lesson(db, review, thread)
    except lessons_service.LessonError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return LessonDraftResponse(**draft)


@router.post("/{review_id}/threads/{thread_id}/lesson", response_model=LessonApplyResponse)
def apply_lesson(
    review_id: int,
    thread_id: int,
    payload: LessonApplyRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> LessonApplyResponse:
    """Write the reviewer-approved lesson into the chosen foundation and record attribution."""
    review, thread = _lesson_thread(db, user.id, review_id, thread_id)
    try:
        lesson = lessons_service.apply_lesson(
            db,
            review,
            thread,
            foundation_id=payload.foundation_id,
            title=payload.title,
            body=payload.body,
        )
    except lessons_service.LessonError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except SkillError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return LessonApplyResponse(
        path=lesson.path, foundation=lesson.foundation, lesson_id=lesson.id
    )
