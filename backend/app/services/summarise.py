"""Best-effort summarisation + pruning of review threads before publishing.

One model pass rewrites each thread as a short, self-contained GitHub comment and may mark a
thread for removal when the AI finding was withdrawn during the conversation. The pass never
blocks publishing: `None` means "fall back to the deterministic collation".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.llm_call import LLMPurpose
from app.models.review import CodeReview, MessageRole, ReviewThread, ThreadRound
from app.services import keys_service, llm_service, prompts, skill_loader, skills_service
from app.services.diff_parser import language_hints
from app.services.llm_service import LLMError
from app.services.skills_service import SkillError

logger = logging.getLogger(__name__)

MAX_THREADS_PER_CALL = 30
MAX_MESSAGE_CHARS = 900
MAX_PROMPT_CHARS = 40_000

SUMMARISE_CONTRACT = """
# Task

For each review thread below, decide how it should appear in the published GitHub review.

Return ONLY this JSON object:

{
  "threads": [
    { "thread_id": 21, "summary": "Markdown comment for GitHub.", "drop": false },
    { "thread_id": 43, "summary": "", "drop": true, "reason": "withdrawn during discussion" }
  ]
}

Rules:
- `summary` is one self-contained Markdown comment, at most 120 words, that a developer can read
  on GitHub without seeing this conversation: what the problem was and what the outcome is.
  Keep the original severity prefix (`**High** — …`).
- `drop` is true ONLY when the conversation shows the reviewer pushed back and you agreed the
  code is fine as written, or the finding became obsolete. Dropped threads are NOT posted.
- `drop` is false when the issue still stands, partially stands, or the discussion is unresolved.
- Use the exact `thread_id` numbers given. Never invent ids.
""".strip()


ROUND_SUMMARY_CONTRACT = """
# Task

Write the single GitHub comment that publishes this round of one review thread.

Return ONLY this JSON object:

{ "summary": "Markdown comment for GitHub." }

Rules:
- One self-contained Markdown comment, at most 120 words, that a developer can read on GitHub
  without having seen this conversation. No greeting, no "as discussed", no meta commentary.
- First round of an AI finding: state the problem, where it is, and the agreed fix, keeping the
  original severity prefix (`**High** — …`).
- Reply round: answer the reviewer's last inbound comment directly and state the outcome. Do not
  recap the conversation and do not address this tool.
- Never invent a change, a test or a decision that is not in the conversation.
""".strip()


@dataclass
class SummariseOutcome:
    summaries: dict[int, str] = field(default_factory=dict)
    dropped: set[int] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)


def _transcript(thread: ReviewThread, round_number: int | None = None) -> str:
    lines: list[str] = []
    for message in thread.messages:
        if round_number is not None and (message.round_number or 1) > round_number:
            continue
        speaker = {
            MessageRole.USER: "Reviewer",
            MessageRole.ASSISTANT: "Assistant",
            MessageRole.SYSTEM: "System",
        }.get(message.role, message.role)
        body = message.content.strip()
        if len(body) > MAX_MESSAGE_CHARS:
            body = body[:MAX_MESSAGE_CHARS] + " […truncated]"
        lines.append(f"[{speaker}] {body}")
    return "\n".join(lines)


def build_summarise_prompt(threads: list[ReviewThread]) -> str:
    parts = [
        f"# Pull request review — {len(threads)} thread(s) to finalise",
        "",
        "Decide, per thread, whether it should be published and in what words.",
        "",
    ]
    used = sum(len(part) for part in parts)
    for thread in threads:
        block = (
            f"## thread_id {thread.id} — `{thread.file_path}:{thread.line_number}`\n"
            f"{_transcript(thread)}\n"
        )
        if used + len(block) > MAX_PROMPT_CHARS:
            break
        parts.append(block)
        used += len(block)
    parts.append(SUMMARISE_CONTRACT)
    return "\n".join(parts)


async def summarise_threads(
    db: Session, review: CodeReview, threads: list[ReviewThread]
) -> SummariseOutcome | None:
    """Run the pre-publish pass. Returns None when it cannot be trusted (caller falls back)."""
    if not threads:
        return SummariseOutcome()

    try:
        model = llm_service.parse_model_id(review.model_used or "")
        credentials = keys_service.credentials_for_provider(db, review.user_id, model.provider)
    except (LLMError, keys_service.KeyError) as exc:
        logger.info("Summariser skipped: %s", exc)
        return None

    try:
        foundation = skills_service.get_foundation(review.skill_foundation)
        root = foundation.path
    except SkillError:
        root = None

    bundle = skill_loader.load_bundle(
        language_hints([thread.file_path for thread in threads]), root=root
    )
    system_prompt = prompts.build_discussion_system_prompt(bundle.text) + "\n\n" + SUMMARISE_CONTRACT
    user_prompt = build_summarise_prompt(threads[:MAX_THREADS_PER_CALL])

    try:
        outcome = await llm_service.generate(
            credentials,
            model,
            system_prompt,
            user_prompt,
            json_mode=True,
            purpose=LLMPurpose.SUMMARISE,
            review_id=review.id,
        )
        document = llm_service.extract_json_document(outcome.text)
    except LLMError as exc:
        logger.warning("Summariser failed: %s", exc)
        return None

    entries = document.get("threads") if isinstance(document, dict) else document
    if not isinstance(entries, list):
        logger.warning("Summariser returned an unexpected shape: %r", type(document))
        return None

    by_id = {thread.id: thread for thread in threads}
    outcome = SummariseOutcome()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            thread_id = int(entry.get("thread_id"))
        except (TypeError, ValueError):
            continue
        thread = by_id.get(thread_id)
        if thread is None:
            continue

        summary = entry.get("summary")
        summary = summary.strip() if isinstance(summary, str) else ""
        should_drop = bool(entry.get("drop"))

        thread.summary = summary or None
        thread.dropped = should_drop
        if should_drop:
            outcome.dropped.add(thread_id)
            reason = entry.get("reason")
            if isinstance(reason, str) and reason.strip():
                outcome.warnings.append(f"Thread {thread_id} withdrawn: {reason.strip()}")
        elif not summary:
            outcome.warnings.append(
                f"Thread {thread_id} had no summary; its last message will be used."
            )
        else:
            outcome.summaries[thread_id] = summary

    db.commit()
    return outcome


def build_round_summary_prompt(
    review: CodeReview, thread: ReviewThread, round_row: ThreadRound
) -> str:
    """PR identity, the anchored hunk, the conversation up to this round and its inbound comment."""
    parts = [
        f"# Pull request {review.repo_full_name or 'this pull request'}#{review.pr_number or ''}",
        f"- Thread anchored at: `{thread.file_path}:{thread.line_number}`",
        "",
        "## Diff context",
        thread.diff_hunk or "(no diff context stored)",
        "",
        "## Conversation so far",
        _transcript(thread, round_row.round_number),
        "",
    ]
    inbound = (round_row.inbound_body or "").strip()
    if inbound:
        author = round_row.inbound_author or "reviewer"
        parts.append(f"## Round {round_row.round_number} — inbound comment by @{author}")
        parts.append(inbound[:MAX_MESSAGE_CHARS])
    else:
        parts.append(f"## Round {round_row.round_number}")
        parts.append("First round: this is the AI finding itself, with no inbound comment yet.")
    return "\n".join(parts)


async def summarise_round(
    db: Session, review: CodeReview, thread: ReviewThread, round_row: ThreadRound
) -> tuple[str | None, list[str]]:
    """Rewrite one round as the GitHub comment for it.

    Returns `(text, warnings)`; `text` is None when the pass could not be trusted, and the caller
    falls back to the copilot's reply.
    """
    try:
        model = llm_service.parse_model_id(review.model_used or "")
        credentials = keys_service.credentials_for_provider(db, review.user_id, model.provider)
    except (LLMError, keys_service.KeyError) as exc:
        logger.info("Round summary skipped: %s", exc)
        return None, [f"Could not summarise this round ({exc}); the copilot's text was kept."]

    try:
        foundation = skills_service.get_foundation(review.skill_foundation)
        root = foundation.path
    except SkillError:
        root = None

    bundle = skill_loader.load_bundle(language_hints([thread.file_path]), root=root)
    system_prompt = (
        prompts.build_discussion_system_prompt(bundle.text) + "\n\n" + ROUND_SUMMARY_CONTRACT
    )
    user_prompt = build_round_summary_prompt(review, thread, round_row)

    try:
        outcome = await llm_service.generate(
            credentials,
            model,
            system_prompt,
            user_prompt,
            json_mode=True,
            purpose=LLMPurpose.SUMMARISE,
            review_id=review.id,
            thread_id=thread.id,
        )
        document = llm_service.extract_json_document(outcome.text)
    except LLMError as exc:
        logger.warning("Round summary failed: %s", exc)
        return None, [f"Could not summarise this round ({exc}); the copilot's text was kept."]

    summary = document.get("summary") if isinstance(document, dict) else None
    if not isinstance(summary, str) or not summary.strip():
        logger.warning("Round summary returned an unexpected shape: %r", type(document))
        return None, [
            "Could not summarise this round (unexpected model answer); the copilot's text was kept."
        ]
    return summary.strip(), []
