"""Telemetry: write one `llm_calls` row per provider call, and never fail the caller doing it.

The insert runs in **its own session**, so it cannot join, or poison, the review's transaction: a
review that rolls back still leaves an honest record of the calls it made, and a database error on
this path cannot undo a review, a discussion or a published comment.

`record` is total: it returns `None` and logs a warning on every failure. That is the whole point —
telemetry is advisory, and losing a row is always better than losing a review.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.pricing import estimate_cost
from app.db.session import SessionLocal
from app.models.llm_call import LLMCall

if TYPE_CHECKING:  # the adapter imports this module; keep the type import one-way
    from app.services.llm_service import LLMResult

logger = logging.getLogger(__name__)


def record(
    outcome: "LLMResult",
    *,
    purpose: str,
    review_id: int | None = None,
    thread_id: int | None = None,
) -> None:
    """Persist one call. Counts and latency only — never text (see `models/llm_call.py`)."""
    try:
        cost = estimate_cost(
            outcome.provider,
            outcome.model,
            outcome.prompt_tokens,
            outcome.completion_tokens,
        )
        with SessionLocal() as db:
            db.add(
                LLMCall(
                    review_id=review_id,
                    thread_id=thread_id,
                    purpose=purpose,
                    provider=outcome.provider,
                    model=outcome.model,
                    prompt_tokens=outcome.prompt_tokens,
                    completion_tokens=outcome.completion_tokens,
                    total_tokens=outcome.total_tokens,
                    estimated_cost_usd=cost,
                    latency_ms=outcome.latency_ms,
                    ok=outcome.ok,
                    error_class=outcome.error_class,
                )
            )
            db.commit()
    except Exception as exc:  # noqa: BLE001 - the boundary is the point
        logger.warning(
            "Could not record an LLM call (purpose=%s, provider=%s, model=%s): %s: %s",
            purpose,
            outcome.provider,
            outcome.model,
            exc.__class__.__name__,
            exc,
        )
