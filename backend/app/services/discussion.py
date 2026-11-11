"""Bulk discussion: one model call per updated thread, answered concurrently.

Two transports share one preparation: the JSON endpoint answers everything and returns when
the slowest thread finishes; the SSE endpoint (`stream_discussion`) streams deltas per thread
and persists each completed exchange (user + assistant messages together) in its own short
transaction, so a cancel or a per-thread failure never leaves an orphan user message.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.llm_call import LLMPurpose
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
from app.services.apply_service import recompute_status
from app.services.diff_parser import language_hints
from app.services.llm_service import LLMCredentials, LLMError, ModelRef
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

def _prospective_round(thread) -> int:
    """The round `open_scratchpad_round` would open, without opening it."""
    number = max(thread.current_round or 1, 1)
    current = thread.round(number)
    if current is not None and current.status in OPEN_ROUND_STATUSES:
        return number
    return number + 1


async def discuss_threads(
    db: Session, review: CodeReview, entries: list[DiscussThread]
) -> tuple[CodeReview, list[DiscussResult], list[str], bool]:
    """Answer each thread, then refresh the review-level verdict. Never raises for model failures."""
    prepared = prepare_discussion(db, review, entries)

    # Persist the reviewer's messages first: they are real content even if the model fails.
    threads_by_id = {thread.id: thread for thread in review.threads}
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

    async def call(entry: PreparedEntry) -> llm_service.LLMResult:
        return await llm_service.generate(
            prepared.credentials,
            prepared.model,
            prepared.system_prompt,
            entry.user_prompt,
            purpose=LLMPurpose.DISCUSS,
            review_id=review.id,
            thread_id=entry.thread_id,
        )

    outcomes = await asyncio.gather(
        *(call(entry) for entry in prepared.entries),
        return_exceptions=True,
    )

    results: list[DiscussResult] = []
    for entry, outcome in zip(prepared.entries, outcomes):
        thread = threads_by_id[entry.thread_id]
        if isinstance(outcome, BaseException):
            message = str(outcome)
            logger.warning("Discussion failed for thread %s: %s", thread.id, message)
            results.append(
                DiscussResult(
                    thread_id=thread.id,
                    ok=False,
                    error=message,
                    references=entry.reference_ordinals,
                )
            )
            continue
        thread.messages.append(
            ThreadMessage(
                role=MessageRole.ASSISTANT,
                content=outcome.text.strip(),
                round_number=round_numbers[entry.thread_id],
            )
        )
        results.append(
            DiscussResult(
                thread_id=thread.id,
                ok=True,
                references=entry.reference_ordinals,
            )
        )

    # The first successful discussion turns a fresh draft into an in-discussion review.
    if any(result.ok for result in results):
        if review.status == ReviewStatus.DRAFT:
            review.status = ReviewStatus.IN_DISCUSSION
    db.commit()

    warnings, refreshed = await _refresh_opinion(db, review)
    db.refresh(review)
    return review, results, warnings, refreshed


@dataclass
class PreparedEntry:
    thread_id: int
    message: str
    user_prompt: str
    reference_ordinals: list[int]


@dataclass
class PreparedDiscussion:
    """Everything a discussion transport needs, detached from the request session."""

    review_id: int
    credentials: LLMCredentials
    model: ModelRef
    system_prompt: str
    entries: list[PreparedEntry]


def prepare_discussion(
    db: Session, review: CodeReview, entries: list[DiscussThread]
) -> PreparedDiscussion:
    """Validate the batch and build the prompts the JSON and streaming transports share."""
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

    bundle = skill_loader.load_bundle(
        language_hints([threads_by_id[entry.thread_id].file_path for entry in entries]),
        root=_foundation_root(review),
    )
    system_prompt = prompts.build_discussion_system_prompt(bundle.text)
    from app.services.references import find_references

    review_threads = list(review.threads)
    prepared_entries = []
    for entry in entries:
        thread = threads_by_id[entry.thread_id]
        references = find_references(entry.message, review_threads)
        # The incoming message is not persisted yet (the streaming transport might never be:
        # a failed or cancelled thread writes nothing), so it joins the transcript as a
        # transient tail — the prompt must end with what the reviewer just asked.
        pending = ThreadMessage(
            role=MessageRole.USER,
            content=entry.message,
            round_number=_prospective_round(thread),
        )
        prompt_view = SimpleNamespace(
            file_path=thread.file_path,
            line_number=thread.line_number,
            diff_hunk=thread.diff_hunk,
            rounds=list(thread.rounds),
            messages=[*thread.messages, pending],
        )
        prepared_entries.append(
            PreparedEntry(
                thread_id=entry.thread_id,
                message=entry.message,
                user_prompt=prompts.build_discussion_user_prompt(
                    review.repo_full_name or "unknown/repository",
                    review.pr_number,
                    prompt_view,
                    references=references,
                ),
                reference_ordinals=[ref.ordinal for ref in references],
            )
        )
    return PreparedDiscussion(
        review_id=review.id,
        credentials=credentials,
        model=model,
        system_prompt=system_prompt,
        entries=prepared_entries,
    )


async def _refresh_opinion(db: Session, review: CodeReview) -> tuple[list[str], bool]:
    """Re-evaluate the review-level verdict after a discussion round; never raises."""
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

    # Only recompute when the review was already applied; otherwise trust the discuss write.
    # A fresh draft that just received a successful response must stay in_discussion, not be
    # recomputed back to draft because it has no published content yet.
    if review.status == ReviewStatus.APPLIED:
        review.status = recompute_status(review)
    db.commit()
    return warnings, refreshed


def _persist_exchange(review_id: int, thread_id: int, user_text: str, assistant_text: str) -> int:
    """Write one completed exchange atomically — user message, reply, round, status — in its
    own short transaction. Called only when the model finished, so a failed or cancelled
    thread leaves nothing behind. Returns the assistant message id."""
    with SessionLocal() as db:
        review = db.get(CodeReview, review_id)
        if review is None:
            raise PipelineError("Review not found.", 404)
        thread = next((thread for thread in review.threads if thread.id == thread_id), None)
        if thread is None:
            raise PipelineError("Thread not found.", 404)
        number = open_scratchpad_round(thread)
        thread.messages.append(
            ThreadMessage(role=MessageRole.USER, content=user_text, round_number=number)
        )
        reply = ThreadMessage(
            role=MessageRole.ASSISTANT, content=assistant_text, round_number=number
        )
        thread.messages.append(reply)
        if review.status == ReviewStatus.DRAFT:
            review.status = ReviewStatus.IN_DISCUSSION
        db.flush()
        message_id = reply.id
        db.commit()
        return message_id


async def stream_discussion(prepared: PreparedDiscussion) -> AsyncIterator[dict]:
    """Yield discussion events as they happen; one task per thread, one queue back.

    Each task runs one streaming model call and, on completion, persists the exchange in its
    own short transaction. A failed thread yields `thread_error` and persists nothing; a
    cancelled stream cancels every task and the in-flight threads persist nothing either.
    The terminal `done` is only produced when the stream runs to completion.
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def run(entry: PreparedEntry) -> None:
        queue.put_nowait({"type": "thread_started", "thread_id": entry.thread_id})
        try:
            result = await llm_service.stream(
                prepared.credentials,
                prepared.model,
                prepared.system_prompt,
                entry.user_prompt,
                on_delta=lambda chunk: queue.put_nowait(
                    {"type": "delta", "thread_id": entry.thread_id, "text": chunk}
                ),
                purpose=LLMPurpose.DISCUSS,
                review_id=prepared.review_id,
                thread_id=entry.thread_id,
            )
        except Exception as exc:
            logger.warning("Discussion failed for thread %s: %s", entry.thread_id, exc)
            queue.put_nowait(
                {
                    "type": "thread_error",
                    "thread_id": entry.thread_id,
                    "error": str(exc),
                    "references": entry.reference_ordinals,
                }
            )
            return
        message_id = _persist_exchange(
            prepared.review_id, entry.thread_id, entry.message, result.text.strip()
        )
        queue.put_nowait(
            {
                "type": "thread_done",
                "thread_id": entry.thread_id,
                "message_id": message_id,
                "references": entry.reference_ordinals,
            }
        )

    tasks = [asyncio.create_task(run(entry)) for entry in prepared.entries]
    remaining = len(tasks)
    answered = 0
    try:
        while remaining:
            event = await queue.get()
            if event["type"] == "thread_done":
                remaining -= 1
                answered += 1
            elif event["type"] == "thread_error":
                remaining -= 1
            yield event

        with SessionLocal() as db:
            review = db.get(CodeReview, prepared.review_id)
            if review is None:
                yield {
                    "type": "done",
                    "answered": answered,
                    "failed": len(tasks) - answered,
                    "opinion_refreshed": False,
                    "warnings": ["The review was deleted while the discussion was running."],
                }
                return
            warnings, refreshed = await _refresh_opinion(db, review)
        yield {
            "type": "done",
            "answered": answered,
            "failed": len(tasks) - answered,
            "opinion_refreshed": refreshed,
            "warnings": warnings,
        }
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
