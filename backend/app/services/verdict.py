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
from app.models.review import CodeReview, ReviewStatus
from app.models.verdict_pushback import VerdictPushback
from app.models.watch import ReviewTrigger
from app.services import keys_service, llm_service, prompts, skill_loader, skills_service
from app.services.diff_parser import language_hints
from app.services.llm_service import LLMError
from app.services.skills_service import SkillError

logger = logging.getLogger(__name__)

MAX_RATIONALE_CHARS = 240
MAX_PUSHBACK_RESPONSE_CHARS = 600


class VerdictError(Exception):
    """A push-back the operator can act on: no opinion yet, read-only review, provider failure."""

    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class VerdictOutcome:
    verdict: str
    confidence: int | None
    rationale: str | None


@dataclass(frozen=True)
class PushbackOutcome:
    """One answer to a push-back: whether the model moved, and to what."""

    agrees: bool
    verdict: str
    confidence: int | None
    response: str


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


def _normalise_response(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    return text[:MAX_PUSHBACK_RESPONSE_CHARS] if text else None


def parse_pushback(document) -> PushbackOutcome | None:
    """Validate a push-back answer; the verdict and the response are both required."""
    if not isinstance(document, dict):
        return None
    agrees = document.get("agrees")
    if not isinstance(agrees, bool):
        return None
    verdict = _normalise_verdict(document.get("verdict"))
    response = _normalise_response(document.get("response"))
    if verdict is None or response is None:
        return None
    return PushbackOutcome(
        agrees=agrees,
        verdict=verdict,
        confidence=_normalise_confidence(document.get("confidence")),
        response=response,
    )


async def evaluate(db: Session, review: CodeReview) -> VerdictOutcome | None:
    """One model call over every thread. Returns None when the answer cannot be used."""
    threads = list(review.threads)
    if not threads:
        return None
    return await _ask(
        db,
        review,
        paths=[thread.file_path for thread in threads],
        user_prompt=prompts.build_verdict_prompt(threads),
    )


async def evaluate_findings(db: Session, review: CodeReview, findings) -> VerdictOutcome | None:
    """One model call over a multi-part review's merged findings (anchored, pre-persistence).

    An empty list is still worth asking about: a large change where no part found anything should
    get a verdict, and "no findings" is exactly what the contract's `APPROVE` is for.
    """
    return await _ask(
        db,
        review,
        paths=[finding.path for finding in findings],
        user_prompt=prompts.build_findings_verdict_prompt(findings),
    )


async def _ask(
    db: Session, review: CodeReview, *, paths: list[str], user_prompt: str
) -> VerdictOutcome | None:
    """Shared body: resolve the model and its credentials, then one JSON-shaped call.

    The re-evaluation is advisory, so a missing key or a failed call is logged and keeps the old
    opinion — the push-back caller is the one that has to surface it.
    """
    try:
        document = await _ask_document(db, review, paths=paths, user_prompt=user_prompt)
    except (LLMError, keys_service.KeyError) as exc:
        logger.info("Verdict re-evaluation skipped: %s", getattr(exc, "detail", exc))
        return None
    outcome = parse_outcome(document)
    if outcome is None:
        logger.warning("Verdict re-evaluation returned an unusable answer for review %s", review.id)
    return outcome


async def _ask_document(
    db: Session,
    review: CodeReview,
    *,
    paths: list[str],
    user_prompt: str,
    purpose: str = LLMPurpose.VERDICT,
) -> dict | list | None:
    """One JSON-shaped call over the review with the verdict system prompt.

    Raises `LLMError` for a bad model id, a failed call or an unreadable body, and
    `keys_service.KeyError` when the provider has no credential — the push-back caller maps both to
    an answer the reviewer can act on, while the advisory re-evaluation swallows them.
    """
    model = llm_service.parse_model_id(review.model_used or "")
    credentials = await keys_service.credentials_for_provider(db, review.user_id, model.provider)

    bundle = skill_loader.load_bundle(language_hints(paths), root=_foundation_root(review))
    system_prompt = (
        prompts.build_discussion_system_prompt(bundle.text) + "\n\n" + prompts.VERDICT_CONTRACT
    )

    outcome = await llm_service.generate(
        credentials,
        model,
        system_prompt,
        user_prompt,
        json_mode=True,
        purpose=purpose,
        review_id=review.id,
    )
    return llm_service.extract_json_document(outcome.text)


def apply_outcome(review: CodeReview, outcome: VerdictOutcome) -> None:
    review.suggested_verdict = outcome.verdict
    review.confidence_percentage = outcome.confidence
    review.suggested_verdict_note = outcome.rationale


async def push_back(
    db: Session, review: CodeReview, argument: str
) -> tuple[VerdictPushback, CodeReview]:
    """Ask the model to reconsider its opinion against the reviewer's argument.

    Nothing is written when the call fails: the caller gets a `VerdictError` and the stored opinion
    keeps standing. An agreeing answer replaces the opinion (verdict, confidence and note); a
    disagreeing one is recorded as a rebuttal and changes nothing.
    """
    text = " ".join((argument or "").split()).strip()
    if not text:
        raise VerdictError("Write why you disagree before pushing back.", 422)
    if review.trigger == ReviewTrigger.COMPARISON:
        raise VerdictError(
            "A comparison review is read-only: push back on the primary review instead.", 409
        )
    if review.status == ReviewStatus.RUNNING:
        raise VerdictError("The review is still running: push back once it has an opinion.", 409)
    if not review.suggested_verdict:
        raise VerdictError("This review has no AI opinion to push back on yet.", 409)

    threads = list(review.threads)
    if not threads:
        raise VerdictError("This review has no findings to re-read.", 409)

    try:
        document = await _ask_document(
            db,
            review,
            paths=[thread.file_path for thread in threads],
            user_prompt=prompts.build_verdict_pushback_prompt(review, threads, text),
            purpose=LLMPurpose.PUSHBACK,
        )
    except keys_service.KeyError as exc:
        raise VerdictError(exc.detail, 422) from exc
    except LLMError as exc:
        raise VerdictError(f"The model did not answer: {exc}", 502) from exc

    outcome = parse_pushback(document)
    if outcome is None:
        raise VerdictError(
            "The model's answer could not be read, so the opinion is unchanged. Try again.", 502
        )

    row = VerdictPushback(
        review_id=review.id,
        argument=text,
        previous_verdict=review.suggested_verdict,
        previous_confidence=review.confidence_percentage,
        agrees=outcome.agrees,
        verdict=outcome.verdict,
        confidence=outcome.confidence,
        response=outcome.response,
    )
    db.add(row)
    if outcome.agrees:
        apply_outcome(
            review,
            VerdictOutcome(
                verdict=outcome.verdict,
                confidence=outcome.confidence,
                rationale=_normalise_rationale(outcome.response),
            ),
        )
    db.commit()
    db.refresh(row)
    db.refresh(review)
    return row, review
