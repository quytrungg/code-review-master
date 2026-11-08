"""Bulk discussion: one model call per updated thread, answered concurrently."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.review import (
    CodeReview,
    MessageRole,
    ReviewStatus,
    RoundStatus,
    ThreadMessage,
    ThreadRound,
)
from app.schemas.review import DiscussResult, DiscussThread
from app.services import keys_service, llm_service, prompts, skill_loader, skills_service, verdict
from app.services.diff_parser import language_hints
from app.services.llm_service import LLMError
from app.services.review_pipeline import PipelineError
from app.services.skills_service import SkillError

logger = logging.getLogger(__name__)


def _foundation_root(review: CodeReview) -> Path | None:
    """Skill root for this review; falls back to the default if the folder is gone."""
    try:
        return skills_service.get_foundation(review.skill_foundation).path
    except SkillError:
        logger.warning(
            "Foundation %s is missing for review %s; using the default",
            review.skill_foundation,
            review.id,
        )
        return None


OPEN_ROUND_STATUSES = (RoundStatus.DRAFTING, RoundStatus.PENDING_APPLY)


def open_scratchpad_round(thread) -> int:
    """Return the round the conversation belongs to, opening one when the last is closed.

    A published round (an imported GitHub thread's history, or a reply already posted) cannot be
    edited, so a new draft round is opened to hold the copilot exchange and the reply.
    """
    number = max(thread.current_round or 1, 1)
    current = thread.round(number)
    if current is not None and current.status in OPEN_ROUND_STATUSES:
        return number
    number += 1
    thread.rounds.append(ThreadRound(round_number=number, status=RoundStatus.DRAFTING))
    thread.current_round = number
    return number


async def discuss_threads(
    db: Session, review: CodeReview, entries: list[DiscussThread]
) -> tuple[CodeReview, list[DiscussResult], list[str], bool]:
    """Answer each thread, then refresh the review-level verdict. Never raises for model failures."""
    threads_by_id = {thread.id: thread for thread in review.threads}
    for entry in entries:
        if entry.thread_id not in threads_by_id:
            raise PipelineError(f"Thread {entry.thread_id} does not belong to this review.", 400)

    try:
        model = llm_service.parse_model_id(review.model_used or "")
    except LLMError as exc:
        raise PipelineError(str(exc), 422) from exc
    try:
        credentials = keys_service.credentials_for_provider(db, review.user_id, model.provider)
    except keys_service.KeyError as exc:
        raise PipelineError(exc.detail, exc.status_code) from exc

    # Persist the reviewer's messages first: they are real content even if the model fails.
    round_numbers = {
        entry.thread_id: open_scratchpad_round(threads_by_id[entry.thread_id])
        for entry in entries
    }
    for entry in entries:
        threads_by_id[entry.thread_id].messages.append(
            ThreadMessage(
                role=MessageRole.USER,
                content=entry.message,
                round_number=round_numbers[entry.thread_id],
            )
        )
    db.commit()

    bundle = skill_loader.load_bundle(
        language_hints([threads_by_id[entry.thread_id].file_path for entry in entries]),
        root=_foundation_root(review),
    )
    system_prompt = prompts.build_discussion_system_prompt(bundle.text)
    from app.services.references import find_references

    review_threads = list(review.threads)
    references = {
        entry.thread_id: find_references(entry.message, review_threads) for entry in entries
    }
    user_prompts = [
        prompts.build_discussion_user_prompt(
            review.repo_full_name or "unknown/repository",
            review.pr_number,
            threads_by_id[entry.thread_id],
            references=references[entry.thread_id],
        )
        for entry in entries
    ]

    async def call(prompt: str) -> str:
        return await llm_service.generate(credentials, model, system_prompt, prompt)

    outcomes = await asyncio.gather(
        *(call(prompt) for prompt in user_prompts), return_exceptions=True
    )

    results: list[DiscussResult] = []
    for entry, outcome in zip(entries, outcomes):
        thread = threads_by_id[entry.thread_id]
        if isinstance(outcome, BaseException):
            message = str(outcome)
            logger.warning("Discussion failed for thread %s: %s", thread.id, message)
            results.append(
                DiscussResult(
                    thread_id=thread.id,
                    ok=False,
                    error=message,
                    references=[ref.ordinal for ref in references[entry.thread_id]],
                )
            )
            continue
        thread.messages.append(
            ThreadMessage(
                role=MessageRole.ASSISTANT,
                content=outcome.strip(),
                round_number=round_numbers[entry.thread_id],
            )
        )
        results.append(
            DiscussResult(
                thread_id=thread.id,
                ok=True,
                references=[ref.ordinal for ref in references[entry.thread_id]],
            )
        )

    if any(result.ok for result in results):
        review.status = ReviewStatus.IN_DISCUSSION
    db.commit()

    # The opinion is a snapshot from ingest; the discussion may have changed it.
    warnings: list[str] = []
    refreshed = False
    outcome = await verdict.evaluate(db, review)
    if outcome is None:
        warnings.append(
            "The AI opinion could not be re-evaluated this round; the previous verdict was kept."
        )
    else:
        verdict.apply_outcome(review, outcome)
        db.commit()
        refreshed = True

    db.refresh(review)
    return review, results, warnings, refreshed
