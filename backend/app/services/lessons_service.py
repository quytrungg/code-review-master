"""A lesson recorded from a pushed-back finding, written into a skill foundation.

Initiative 6, beta-gated by `settings.beta_features.push_back_lessons` (phase 35). Two calls:
`draft_lesson` asks the review's model to turn the rejected finding into a short reusable rule
(one ledger row, `purpose=lesson`), and `apply_lesson` writes the reviewer-approved text as one
markdown file into the chosen foundation plus a `skill_lessons` attribution row. The lesson
lands before the push-back decision is sent, so a failed draft or write never blocks the push
back.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.lesson import SkillLesson
from app.models.llm_call import LLMPurpose
from app.models.review import CodeReview, ReviewThread
from app.services import keys_service, llm_service, skills_service
from app.services.llm_service import LLMError
from app.services.skills_service import SkillError

logger = logging.getLogger(__name__)


class LessonError(Exception):
    """Same shape as `review_pipeline.PipelineError`, without importing that module — it sits
    inside a fragile import cycle (`review_pipeline → thread_sync → apply_service`)."""

    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


# The phase 35 flag id this feature is gated behind.
LESSON_FLAG = "push_back_lessons"

_DRAFT_SYSTEM = """You turn a rejected code-review finding into one short, reusable rule for the \
reviewer's private skill library, so the same false positive is not raised again.

Return only a JSON object: {"title": string, "body": string}.

- "title": at most 80 characters, imperative, specific enough to recognise at a glance.
- "body": 2-5 sentences of guidance to a future reviewer, starting with one scope line of the \
form "Applies to: <file types or path patterns>". Say what to check before raising this kind \
of finding, and why it was wrong here.
- Write the rule, not the argument: no mention of this review, thread, or the model."""

_MAX_MESSAGE_CHARS = 1200
_MAX_MESSAGES = 10


def owned_thread(review: CodeReview, thread_id: int) -> ReviewThread:
    for thread in review.threads:
        if thread.id == thread_id:
            return thread
    raise LessonError("That thread does not belong to this review.", 404)


def _thread_context(thread: ReviewThread) -> str:
    """The finding and its discussion, bounded — the same data the discussion already sent."""
    lines = [f"File: {thread.file_path}", f"Anchored line: {thread.line_number}"]
    if thread.summary:
        lines.append(f"Finding summary: {thread.summary}")
    if thread.diff_hunk:
        lines.append(f"Diff hunk:\n{thread.diff_hunk[:_MAX_MESSAGE_CHARS]}")
    for message in thread.messages[-_MAX_MESSAGES:]:
        text = message.content[:_MAX_MESSAGE_CHARS]
        lines.append(f"{message.role}: {text}")
    return "\n\n".join(lines)


async def draft_lesson(db: Session, review: CodeReview, thread: ReviewThread) -> dict[str, str]:
    """One model call over the finding: a {title, body} rule the reviewer can edit."""
    try:
        model = llm_service.parse_model_id(review.model_used or "")
        credentials = keys_service.credentials_for_provider(db, review.user_id, model.provider)
    except (LLMError, keys_service.KeyError) as exc:
        detail = getattr(exc, "detail", str(exc))
        raise LessonError(
            f"The lesson could not be drafted: {detail} Push back anyway, or pick the wording by hand.",
            502,
        ) from exc

    try:
        outcome = await llm_service.generate(
            credentials,
            model,
            _DRAFT_SYSTEM,
            _thread_context(thread),
            json_mode=True,
            purpose=LLMPurpose.LESSON,
            review_id=review.id,
            thread_id=thread.id,
        )
        document = llm_service.extract_json_document(outcome.text)
        if not isinstance(document, dict):
            raise ValueError("the draft was not a JSON object")
        title = str(document.get("title") or "").strip()
        body = str(document.get("body") or "").strip()
    except (LLMError, ValueError, AttributeError) as exc:
        logger.warning("Lesson draft failed for thread %s: %s", thread.id, exc)
        raise LessonError(
            "The lesson could not be drafted. Push back anyway, or write the rule by hand.",
            502,
        ) from exc
    if not title or not body:
        raise LessonError(
            "The draft came back empty. Push back anyway, or write the rule by hand.", 502
        )
    return {"title": title, "body": body}


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:80] or "lesson"


def _lesson_path(thread: ReviewThread, title: str) -> str:
    """`lessons/<filetype>-<slug>.md` — the filetype token is what makes `skill_loader._score`
    select the file for future reviews of the same file type (see INITIATIVES.md §6)."""
    suffix = Path(thread.file_path).suffix.lstrip(".").lower()
    filetype = re.sub(r"[^a-z0-9]", "", suffix) or "general"
    return skills_service.sanitize_relative_path(f"lessons/{filetype}-{_slugify(title)}.md")


def apply_lesson(
    db: Session,
    review: CodeReview,
    thread: ReviewThread,
    *,
    foundation_id: str,
    title: str,
    body: str,
) -> SkillLesson:
    """Write the reviewer-approved lesson into the chosen foundation and record attribution."""
    title = (title or "").strip()
    body = (body or "").strip()
    if not title or not body:
        raise LessonError("A lesson needs both a title and a body.", 422)

    skills_service.require_writable()  # SkillError 403 on serverless — the UI offers copy instead.
    info = skills_service.require_foundation(foundation_id)

    relative = _lesson_path(thread, title)
    target = info.path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    stem, suffix = target.stem, target.suffix
    counter = 2
    while target.exists():
        target = target.with_name(f"{stem}-{counter}{suffix}")
        counter += 1

    header = (
        f"<!-- Lesson from review #{review.id}, thread #{thread.id} "
        f"— pushed back {datetime.now(timezone.utc).date().isoformat()} -->\n"
    )
    target.write_text(f"{header}\n# {title}\n\n{body}\n", encoding="utf-8")

    lesson = SkillLesson(
        user_id=review.user_id,
        review_id=review.id,
        thread_id=thread.id,
        foundation=info.id,
        path=str(target.relative_to(info.path)),
        title=title,
    )
    db.add(lesson)
    db.commit()
    db.refresh(lesson)
    return lesson


__all__ = ["LESSON_FLAG", "apply_lesson", "draft_lesson", "owned_thread"]
