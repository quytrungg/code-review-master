"""Side-by-side comparison: merge two reviews of one diff, and price the second run.

Matching is deliberately conservative: same file, at most `LINE_TOLERANCE` lines apart, and either
the same phase-41 normalised key or the exact same line. Two models often report the same defect at
neighbouring lines; they also report different defects on nearby lines, and merging those would
turn "both models found this" into a lie. `both` is evidence, not a score — the copy says so.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.pricing import estimate_cost, price_for
from app.models.review import (
    CodeReview,
    MessageRole,
    ReviewThread,
    ThreadOrigin,
)
from app.models.watch import ReviewTrigger
from app.services import analytics, llm_service
from app.services.finding_search import normalise

LINE_TOLERANCE = 2
SNIPPET_CHARS = 240


@dataclass
class ComparisonPair:
    primary: CodeReview
    comparison: CodeReview


def _key(thread: ReviewThread) -> str:
    if thread.norm_key:
        return thread.norm_key
    for message in thread.messages:
        if message.role == MessageRole.ASSISTANT:
            return normalise(message.content)
    return ""


def _snippet(thread: ReviewThread) -> str:
    for message in thread.messages:
        if message.role == MessageRole.ASSISTANT and (message.content or "").strip():
            return " ".join(message.content.split())[:SNIPPET_CHARS]
    return ""


def _item(thread: ReviewThread, review: CodeReview) -> dict:
    return {
        "review_id": review.id,
        "thread_id": thread.id,
        "file_path": thread.file_path,
        "line_number": thread.line_number,
        "origin": thread.origin,
        "snippet": _snippet(thread),
    }


def _mergeable(primary: ReviewThread, other: ReviewThread) -> tuple[int, int] | None:
    """`(score, delta)` when the two threads describe the same defect, else `None`."""
    if primary.file_path != other.file_path:
        return None
    delta = abs(primary.line_number - other.line_number)
    if delta > LINE_TOLERANCE:
        return None
    primary_key, other_key = _key(primary), _key(other)
    if primary_key and primary_key == other_key:
        return 0, delta
    if delta == 0:
        # Same line, no shared key: the anchor is the evidence.
        return 1, delta
    return None


def _findings(review: CodeReview) -> list[ReviewThread]:
    return [
        thread
        for thread in review.threads
        if thread.origin in (ThreadOrigin.AI_GENERATED, ThreadOrigin.CHECK)
    ]


def merge(primary: CodeReview, comparison: CodeReview) -> dict:
    """Bucket the two sets of findings into both / primary-only / comparison-only."""
    primary_threads = _findings(primary)
    comparison_threads = _findings(comparison)
    used: set[int] = set()
    both: list[dict] = []
    primary_only: list[ReviewThread] = []

    for thread in primary_threads:
        best: tuple[int, int, int, ReviewThread] | None = None
        for index, candidate in enumerate(comparison_threads):
            if index in used:
                continue
            score = _mergeable(thread, candidate)
            if score is None:
                continue
            ranked = (score[0], score[1], index, candidate)
            if best is None or ranked[:2] < best[:2]:
                best = ranked
        if best is None:
            primary_only.append(thread)
            continue
        index, match = best[2], best[3]
        used.add(index)
        both.append(
            {
                "primary_thread_id": thread.id,
                "comparison_thread_id": match.id,
                "file_path": thread.file_path,
                "primary_line": thread.line_number,
                "comparison_line": match.line_number,
                "snippet": _snippet(thread) or _snippet(match),
            }
        )

    comparison_only = [
        thread for index, thread in enumerate(comparison_threads) if index not in used
    ]
    return {
        "primary": {
            "id": primary.id,
            "model_used": primary.model_used,
            "thread_count": len(primary_threads),
        },
        "comparison": {
            "id": comparison.id,
            "model_used": comparison.model_used,
            "thread_count": len(comparison_threads),
        },
        "both": both,
        "primary_only": [_item(thread, primary) for thread in primary_only],
        "comparison_only": [_item(thread, comparison) for thread in comparison_only],
        "line_tolerance": LINE_TOLERANCE,
    }


def find_pair(db: Session, user_id: int, review: CodeReview) -> ComparisonPair | None:
    """Resolve either side of a comparison to `(primary, comparison)`; `None` when there is none."""
    if review.trigger == ReviewTrigger.COMPARISON and review.parent_review_id:
        primary = db.scalars(
            select(CodeReview).where(
                CodeReview.id == review.parent_review_id, CodeReview.user_id == user_id
            )
        ).first()
        if primary is None:
            return None
        return ComparisonPair(primary=primary, comparison=review)

    sibling = db.scalars(
        select(CodeReview)
        .where(
            CodeReview.parent_review_id == review.id,
            CodeReview.user_id == user_id,
            CodeReview.trigger == ReviewTrigger.COMPARISON,
        )
        .order_by(CodeReview.created_at.desc(), CodeReview.id.desc())
    ).first()
    if sibling is None:
        return None
    return ComparisonPair(primary=review, comparison=sibling)


def estimate(db: Session, review: CodeReview, model_id: str) -> dict:
    """Price the second run from the primary's measured tokens — an estimate, never a quote."""
    model = llm_service.parse_model_id(model_id)  # LLMError -> the route maps it to 422
    usage = analytics.review_usage(db, review.id)
    cost = estimate_cost(
        model.provider, model.name, usage.prompt_tokens, usage.completion_tokens
    )
    if usage.total_tokens <= 0:
        note = (
            "This review has no recorded model usage yet, so the comparison cannot be priced "
            "in advance."
        )
    elif price_for(model.name) is None and model.provider not in ("ollama-local",):
        note = (
            f"No published price for {model.name}; the run is estimated in tokens only. "
            "The figure comes from the primary review's measured usage."
        )
    else:
        note = (
            f"Estimated from review #{review.id}'s measured usage "
            f"({usage.total_tokens:,} tokens) at list prices."
        )
    return {
        "model": model.id,
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "estimated_cost_usd": cost,
        "note": note,
    }
