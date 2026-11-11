"""Skill evolution: turn a foundation's recent review friction into concrete guideline edits.

The review history already records every moment the reviewer disagreed with the model: the
push-back, the withdrawn finding, the message the reviewer rewrote before publishing. Nothing
read that record back — the guidelines that caused the friction stayed exactly as they were, so
the same false positive was raised again.

This module closes that loop in three steps:

1. **Aggregate** the account's recent reviews and score every thread for friction.
2. **Condense** the friction into one line per thread, each carrying its review id.
3. **Curate**: one meta-model call turns the rules plus the friction into proposed file edits.

Everything the model proposes is then validated against the real filesystem before the browser
ever sees it: paths are sanitised, `modify`/`delete` must name an existing file, `create` must
not, the diff is computed against the file *on disk* (not the copy the model echoed back), and
evidence ids are filtered to reviews the caller actually owns. A proposal that fails validation
is dropped with a warning instead of reaching the workbench.
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.db.base import utcnow
from app.models.llm_call import LLMPurpose
from app.models.review import (
    CodeReview,
    MessageRole,
    ReviewThread,
    RoundStatus,
    ThreadOrigin,
    ThreadRound,
)
from app.services import keys_service, llm_service, skills_service
from app.services.llm_service import LLMError

logger = logging.getLogger(__name__)

# How much of one message survives into the condensed history.
EXCERPT_CHARS = 240
# The longest interaction summary kept for one thread.
MAX_THREAD_SUMMARY_CHARS = 700
# Cap on the proposals returned to the browser.
MAX_PROPOSALS = 20


class EvolutionError(Exception):
    """An analysis failure the operator can act on (bad model, missing key, …)."""

    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass
class Interaction:
    """One high-signal thread: what the model said, what the reviewer said, how it ended."""

    review_id: int
    thread_id: int
    file_path: str
    line_number: int
    score: int
    ai_raised: str = ""
    reviewer_said: str = ""
    outcome: str = ""

    def render(self) -> str:
        parts = [
            f"[PR #{self.review_id} · {self.file_path}:{self.line_number}]",
            f"AI raised: {self.ai_raised or '(no finding text)'}",
        ]
        if self.reviewer_said:
            parts.append(f"Reviewer: {self.reviewer_said}")
        if self.outcome:
            parts.append(f"Outcome: {self.outcome}")
        return " -> ".join(parts)


@dataclass
class HistoryDigest:
    """The condensed review history behind one analysis."""

    days: int
    review_count: int = 0
    thread_count: int = 0
    interactions: list[Interaction] = field(default_factory=list)
    text: str = ""
    # The review ids in this window: the only evidence ids a proposal may cite.
    review_ids: list[int] = field(default_factory=list)

    @property
    def interaction_count(self) -> int:
        return len(self.interactions)


@dataclass
class Proposal:
    """A validated, file-level edit proposal."""

    file_path: str
    action: Literal["modify", "create", "delete"]
    rationale: str
    evidence_review_ids: list[int]
    original_content: str
    proposed_content: str
    unified_diff: str


@dataclass
class AnalysisResult:
    """Everything the workbench needs to render one analysis."""

    summary: str
    proposals: list[Proposal]
    digest: HistoryDigest
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- aggregation


def _excerpt(text: str | None, limit: int = EXCERPT_CHARS) -> str:
    body = " ".join((text or "").split())
    if not body:
        return ""
    if len(body) > limit:
        body = body[:limit].rstrip() + "…"
    return body


def _last_assistant_text(thread: ReviewThread, round_number: int | None = None) -> str:
    for message in reversed(thread.messages):
        if message.role != MessageRole.ASSISTANT:
            continue
        if round_number is not None and (message.round_number or 1) != round_number:
            continue
        return message.content.strip()
    return ""


def _reviewer_text(thread: ReviewThread) -> str:
    for message in reversed(thread.messages):
        if message.role == MessageRole.USER:
            return message.content.strip()
    return ""


def _score_thread(thread: ReviewThread) -> int:
    """How much friction this thread carries. Zero means "the rule worked".

    Only *friction* counts. A finding that was accepted without a word of disagreement scores
    zero and is dropped: it teaches nothing about the rules.
    """
    score = 0
    rounds = list(thread.rounds)
    if any(item.status == RoundStatus.RESOLVED_NO_REPLY for item in rounds):
        # The reviewer pushed back: the finding was wrong, irrelevant or badly worded.
        score += 3
    if thread.dropped:
        # An AI finding withdrawn outright.
        score += 2
    if _reviewer_text(thread):
        # The reviewer disagreed, questioned or corrected.
        score += 2
    if len(rounds) > 1 or (thread.current_round or 1) > 1:
        # A debate, not a single click.
        score += 2
    for item in rounds:
        if item.status != RoundStatus.PUBLISHED:
            continue
        final = (item.final_summary or "").strip()
        original = _last_assistant_text(thread, item.round_number)
        if final and original and final != original:
            # The reviewer rewrote the critique before publishing: the wording was wrong.
            score += 2
    return score


def _outcome_of(thread: ReviewThread) -> str:
    rounds = list(thread.rounds)
    if any(item.status == RoundStatus.RESOLVED_NO_REPLY for item in rounds):
        if thread.dropped:
            return "the finding was withdrawn as unnecessary"
        return "the reviewer pushed back; nothing was published"
    published = [item for item in rounds if item.status == RoundStatus.PUBLISHED]
    if published:
        final = (published[-1].final_summary or "").strip()
        if final:
            return f"accepted and published as: {_excerpt(final, 160)}"
        return "accepted and published"
    if rounds:
        return "discussed but not decided"
    return ""


def _foundation_matches(review: CodeReview, foundation_id: str) -> bool:
    used = (review.skill_foundation or "").strip()
    if used == foundation_id:
        return True
    # A review with no recorded foundation ran against the built-in rules.
    return not used and foundation_id == skills_service.DEFAULT_FOUNDATION


def aggregate_history(
    db: Session, user_id: int, foundation_id: str, days: int
) -> HistoryDigest:
    """Collect the account's recent review history for one foundation and condense it.

    Only threads our model authored carry a signal about *our* rules; imported pull-request
    threads are somebody else's discussion and are ignored.
    """
    since = utcnow() - timedelta(days=max(1, days))

    reviews = list(
        db.scalars(
            select(CodeReview)
            .where(
                CodeReview.user_id == user_id,
                CodeReview.created_at >= since,
            )
            .order_by(CodeReview.id)
        )
    )
    matching = [row for row in reviews if _foundation_matches(row, foundation_id)]

    digest = HistoryDigest(days=days, review_count=len(matching))
    if not matching:
        digest.text = "(no reviews in this window used this foundation)"
        return digest

    review_ids = [row.id for row in matching]
    threads = list(
        db.scalars(
            select(ReviewThread)
            .where(
                ReviewThread.review_id.in_(review_ids),
                ReviewThread.origin == ThreadOrigin.AI_GENERATED,
            )
            .options(selectinload(ReviewThread.messages), selectinload(ReviewThread.rounds))
            .order_by(ReviewThread.id)
        )
    )
    digest.thread_count = len(threads)

    review_by_id = {row.id: row for row in matching}
    interactions: list[Interaction] = []
    for thread in threads:
        score = _score_thread(thread)
        if score <= 0:
            # An accepted finding nobody argued with teaches nothing about the rules.
            continue
        interactions.append(
            Interaction(
                review_id=thread.review_id,
                thread_id=thread.id,
                file_path=thread.file_path,
                line_number=thread.line_number,
                score=score,
                ai_raised=_excerpt(_last_assistant_text(thread)),
                reviewer_said=_excerpt(_reviewer_text(thread)),
                outcome=_outcome_of(thread),
            )
        )

    interactions.sort(key=lambda item: (-item.score, item.thread_id))
    digest.interactions = interactions

    budget = get_settings().evolution_history_max_chars
    lines: list[str] = []
    used = 0
    for item in interactions:
        line = item.render()
        if len(line) > MAX_THREAD_SUMMARY_CHARS:
            line = line[:MAX_THREAD_SUMMARY_CHARS].rstrip() + "…"
        if used + len(line) + 1 > budget:
            break
        lines.append(line)
        used += len(line) + 1
    digest.text = "\n".join(lines) if lines else "(no reviewer push-back in this window)"

    # The reviews are referenced by number in the summaries; keep the ids for the evidence filter.
    digest.review_ids = list(review_by_id)
    return digest


# ------------------------------------------------------------------------------- prompting


META_CONTRACT = """
# Task

You are curating a code-review guideline library. Below are the current rules and the recent
review history that shows where those rules misfired. Propose concrete edits to the rule files.

Return ONLY a JSON object — no prose, no markdown fences, no text before or after it:

{
  "analysisSummary": "one paragraph: what pattern you saw and what you changed because of it",
  "fileModifications": [
    {
      "filePath": "references/testing.md",
      "action": "modify",
      "rationale": "why this change, in one or two sentences",
      "evidenceReviewIds": [14, 22],
      "originalContent": "the file's current content, copied verbatim",
      "proposedContent": "the file's content after your change"
    }
  ]
}

Rules:
- `action` is "modify" (the file exists), "create" (a new file) or "delete" (the file should go).
- `filePath` must be copied from the file list below, or be a new `*.md` path for "create".
  Never invent a path, and never write outside the library.
- `originalContent` must be the file's current content, copied verbatim. For "create" it is "".
- `proposedContent` is the complete new content of the file. Keep every rule that still holds;
  change only what the history shows was wrong, ambiguous or missing.
- Propose a change only when the history supports it. Name the review ids that motivated it in
  `evidenceReviewIds` — an empty list means "a general improvement", and you should rarely need it.
- Do not restate the rules you are editing. Edit them.
- If the rules are already matching the team's review patterns, return an EMPTY
  `fileModifications` array and explain in `analysisSummary` why no change is needed. That is a
  valid and useful answer — do not invent a change to look busy.
- Prefer a few high-confidence edits over many speculative ones.
""".strip()


def build_meta_prompt(files: dict[str, str], digest: HistoryDigest) -> tuple[str, str]:
    """The system prompt (role + contract) and the user prompt (rules + history + task)."""
    system_prompt = "\n".join(
        [
            "You are a principal software engineer and the rule curator for this team's code-review",
            "assistant. You read the current review guidelines together with the record of where",
            "they caused friction, and you rewrite the guidelines so the same argument does not",
            "happen twice.",
            "",
            META_CONTRACT,
        ]
    )

    budget = get_settings().evolution_skill_max_chars
    blocks: list[str] = []
    used = 0
    skipped: list[str] = []
    for path in sorted(files):
        content = files[path]
        heading = f"## {path}\n"
        block = f"{heading}\n{content}\n"
        if used + len(block) > budget:
            skipped.append(path)
            continue
        blocks.append(block)
        used += len(block)

    parts = ["# Current review guidelines", ""]
    if blocks:
        parts.extend(blocks)
    else:
        parts.append("(the foundation has no readable rule files)")
    if skipped:
        parts.append(
            f"({len(skipped)} further file(s) were left out of this prompt because of its size: "
            f"{', '.join(skipped[:8])})"
        )
    parts.extend(
        [
            "",
            f"# Review history — last {digest.days} days",
            "",
            f"- {digest.review_count} review(s) used this foundation",
            f"- {digest.thread_count} finding thread(s) in total",
            f"- {digest.interaction_count} thread(s) where the reviewer pushed back",
            "",
            digest.text,
            "",
            "# Your task",
            "",
            "Read the history above. Each line is one finding the model raised and what the reviewer",
            "said about it. Propose the rule edits that would stop those findings from being",
            "raised again, and nothing else.",
        ]
    )
    return system_prompt, "\n".join(parts)


# ------------------------------------------------------------------------------- proposals


def _unified_diff(path: str, original: str, proposed: str) -> str:
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        proposed.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=3,
    )
    return "".join(diff)


def parse_proposals(
    document, files: dict[str, str], review_ids: list[int]
) -> tuple[list[Proposal], list[str]]:
    """Validate a model document against the filesystem and turn it into proposals."""
    warnings: list[str] = []
    proposals: list[Proposal] = []

    if not isinstance(document, dict):
        return [], ["The model returned an unexpected shape; no proposals were usable."]

    entries = document.get("fileModifications")
    if not isinstance(entries, list):
        entries = []
        warnings.append("The model returned no file modifications list.")

    allowed_ids = set(review_ids)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_path = entry.get("filePath")
        if not isinstance(raw_path, str) or not raw_path.strip():
            warnings.append("A proposal without a file path was ignored.")
            continue

        try:
            relative = skills_service.sanitize_relative_path(raw_path)
        except skills_service.SkillError as exc:
            warnings.append(f"Dropped the proposal for '{raw_path}': {exc.detail}")
            continue

        action = entry.get("action")
        if action not in ("modify", "create", "delete"):
            warnings.append(f"Dropped the proposal for '{relative}': unknown action '{action}'.")
            continue
        action = cast(Literal["modify", "create", "delete"], action)

        proposed = entry.get("proposedContent")
        proposed = proposed if isinstance(proposed, str) else ""
        model_original = entry.get("originalContent")
        model_original = model_original if isinstance(model_original, str) else ""

        exists = relative in files
        if action in ("modify", "delete") and not exists:
            warnings.append(
                f"Dropped the proposal for '{relative}': the file is not part of this foundation."
            )
            continue
        if action == "create" and exists:
            warnings.append(
                f"Dropped the proposal for '{relative}': the file already exists, so it is not a "
                "'create'."
            )
            continue

        # The disk is the truth. The model's copy of the original is only used to notice that the
        # file changed under it.
        original = files.get(relative, "")
        if action == "modify" and model_original and model_original != original:
            warnings.append(
                f"'{relative}' changed since the analysis; the diff was computed against the "
                "current file."
            )

        if action == "delete":
            proposed = ""
        if action != "delete" and proposed == original:
            warnings.append(f"Dropped the proposal for '{relative}': it changes nothing.")
            continue
        if action == "modify" and not proposed.strip():
            warnings.append(f"Dropped the proposal for '{relative}': the new content is empty.")
            continue

        evidence_raw = entry.get("evidenceReviewIds")
        evidence: list[int] = []
        if isinstance(evidence_raw, list):
            for value in evidence_raw:
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    continue
                if number in allowed_ids and number not in evidence:
                    evidence.append(number)
        if isinstance(evidence_raw, list) and evidence_raw and not evidence:
            warnings.append(
                f"The proposal for '{relative}' cited review ids outside this window; they were "
                "dropped."
            )

        rationale = entry.get("rationale")
        rationale = rationale.strip() if isinstance(rationale, str) else ""

        proposals.append(
            Proposal(
                file_path=relative,
                action=action,
                rationale=rationale,
                evidence_review_ids=evidence,
                original_content=original,
                proposed_content=proposed,
                unified_diff=_unified_diff(relative, original, proposed),
            )
        )
        if len(proposals) >= MAX_PROPOSALS:
            warnings.append(
                f"Only the first {MAX_PROPOSALS} proposals are shown; the model returned more."
            )
            break

    return proposals, warnings


# ------------------------------------------------------------------------------- the call


async def analyse(
    db: Session,
    user_id: int,
    foundation_id: str,
    days: int,
    model_id: str,
) -> AnalysisResult:
    """Run the whole analysis: aggregate, curate with the model, validate the proposals."""
    try:
        model = llm_service.parse_model_id(model_id)
    except LLMError as exc:
        raise EvolutionError(str(exc), 422) from exc

    try:
        credentials = keys_service.credentials_for_provider(db, user_id, model.provider)
    except keys_service.KeyError as exc:
        raise EvolutionError(exc.detail, exc.status_code) from exc

    try:
        files = skills_service.read_foundation_files(foundation_id)
    except skills_service.SkillError as exc:
        raise EvolutionError(exc.detail, exc.status_code) from exc
    digest = aggregate_history(db, user_id, foundation_id, days)
    system_prompt, user_prompt = build_meta_prompt(files, digest)

    try:
        outcome = await llm_service.generate(
            credentials,
            model,
            system_prompt,
            user_prompt,
            json_mode=True,
            purpose=LLMPurpose.EVOLVE,
        )
    except LLMError as exc:
        raise EvolutionError(str(exc), 502) from exc

    try:
        document = llm_service.extract_json_document(outcome.text)
    except LLMError as exc:
        raise EvolutionError(str(exc), 502) from exc

    proposals, warnings = parse_proposals(document, files, digest.review_ids)

    summary = ""
    if isinstance(document, dict):
        raw_summary = document.get("analysisSummary")
        summary = raw_summary.strip() if isinstance(raw_summary, str) else ""
    if not summary:
        summary = "The model returned no summary for this analysis."
        warnings.append("The model's answer had no analysis summary.")

    if not proposals and not warnings:
        warnings.append(
            "The model found nothing to change. Your guidelines closely match your team's "
            "review patterns."
        )

    return AnalysisResult(
        summary=summary, proposals=proposals, digest=digest, warnings=warnings
    )
