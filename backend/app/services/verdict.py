"""Re-evaluate the AI verdict after a discussion round.

The ingest-time opinion is a snapshot from before the reviewer pushed back. Once replies exist, one
extra model call over the whole review produces the verdict the operator would publish now. The
pass is advisory: any failure keeps the previous opinion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.llm_call import LLMPurpose
from app.models.review import CodeReview
from app.services import keys_service, llm_service, prompts, skill_loader, skills_service
from app.services.diff_parser import language_hints
from app.services.llm_service import LLMError
from app.services.skills_service import SkillError

logger = logging.getLogger(__name__)

MAX_RATIONALE_CHARS = 240


@dataclass(frozen=True)
class VerdictOutcome:
    verdict: str
    confidence: int | None
    rationale: str | None


def _foundation_root(review: CodeReview):
    try:
        return skills_service.get_foundation(review.skill_foundation).path
    except SkillError:
        return None


def _normalise_verdict(value) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().upper().replace("-", "_").replace(" ", "_")
    return candidate if candidate in llm_service.VALID_VERDICTS else None


def _normalise_confidence(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, int(round(number))))


def _normalise_rationale(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip(" -–—")
    return text[:MAX_RATIONALE_CHARS] if text else None


def parse_outcome(document) -> VerdictOutcome | None:
    """Validate a model document; `None` means "do not trust this answer"."""
    if not isinstance(document, dict):
        return None
    verdict = _normalise_verdict(document.get("verdict"))
    if verdict is None:
        return None
    return VerdictOutcome(
        verdict=verdict,
        confidence=_normalise_confidence(document.get("confidence")),
        rationale=_normalise_rationale(document.get("rationale")),
    )


async def evaluate(db: Session, review: CodeReview) -> VerdictOutcome | None:
    """One model call over every thread. Returns None when the answer cannot be used."""
    threads = list(review.threads)
    if not threads:
        return None

    try:
        model = llm_service.parse_model_id(review.model_used or "")
    except LLMError as exc:
        logger.info("Verdict re-evaluation skipped: %s", exc)
        return None

    try:
        credentials = keys_service.credentials_for_provider(db, review.user_id, model.provider)
    except keys_service.KeyError as exc:
        logger.info("Verdict re-evaluation skipped: %s", exc.detail)
        return None

    bundle = skill_loader.load_bundle(
        language_hints([thread.file_path for thread in threads]), root=_foundation_root(review)
    )
    system_prompt = (
        prompts.build_discussion_system_prompt(bundle.text) + "\n\n" + prompts.VERDICT_CONTRACT
    )
    user_prompt = prompts.build_verdict_prompt(threads)

    try:
        outcome = await llm_service.generate(
            credentials,
            model,
            system_prompt,
            user_prompt,
            json_mode=True,
            purpose=LLMPurpose.VERDICT,
            review_id=review.id,
        )
        document = llm_service.extract_json_document(outcome.text)
    except LLMError as exc:
        logger.warning("Verdict re-evaluation failed for review %s: %s", review.id, exc)
        return None

    outcome = parse_outcome(document)
    if outcome is None:
        logger.warning("Verdict re-evaluation returned an unusable answer for review %s", review.id)
    return outcome


def apply_outcome(review: CodeReview, outcome: VerdictOutcome) -> None:
    review.suggested_verdict = outcome.verdict
    review.confidence_percentage = outcome.confidence
    review.suggested_verdict_note = outcome.rationale
