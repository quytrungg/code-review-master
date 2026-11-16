"""Standing review policies: when the tick runs, a matching inbox row starts its own review.

The hard part is the same one `watch_service` solved: two ticks must never start two reviews for
one pull request. A policy does not own a mutable marker per PR, so the claim lives on the cached
inbox row itself — one compare-and-set `UPDATE … SET policy_claim_at = now WHERE linked_review_id
IS NULL AND (policy_claim_at IS NULL OR policy_claim_at < <stale>)`, issued before the review row is
created. Rowcount 0 means another tick owns that PR. The claim is cleared if creation fails, and a
crashed tick's claim expires after `policy_claim_stale_minutes`.

No network call happens while a claim is held: policies read `cached_prs` only, and the ingest
runs outside the session that claimed and created, exactly like a watch tick.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import utcnow
from app.db.session import SessionLocal
from app.models.cached_pr import CachedPR, InboxStatus
from app.models.policy import PolicyInvolvement, ReviewPolicy
from app.models.review import CodeReview, ReviewStatus
from app.models.watch import ReviewTrigger
from app.services import keys_service, llm_service, skills_service

logger = logging.getLogger(__name__)

MAX_ERROR_CHARS = 200
ACTIVE_STATUSES = (ReviewStatus.RUNNING, ReviewStatus.DRAFT, ReviewStatus.IN_DISCUSSION)


class PolicyError(Exception):
    """A policy problem the route maps to a status. Same shape as the pipeline's error."""

    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass
class PolicyTickResult:
    started: list[int] = field(default_factory=list)
    skipped: int = 0
    failed: list[dict] = field(default_factory=list)


def list_policies(db: Session, user_id: int) -> list[ReviewPolicy]:
    return list(
        db.scalars(
            select(ReviewPolicy)
            .where(ReviewPolicy.user_id == user_id)
            .order_by(ReviewPolicy.created_at.desc(), ReviewPolicy.id.desc())
        )
    )


def owned_policy(db: Session, user_id: int, policy_id: int) -> ReviewPolicy | None:
    """Another account's policy is `None` -> the route answers 404, never 403."""
    return db.scalars(
        select(ReviewPolicy).where(
            ReviewPolicy.id == policy_id, ReviewPolicy.user_id == user_id
        )
    ).first()


def _validate(db: Session, user_id: int, model_id: str, foundation_id: str | None) -> tuple[str, str]:
    """Return `(model_id, foundation_id)` after the same checks a review creation makes."""
    try:
        model = llm_service.parse_model_id(model_id)
    except llm_service.LLMError as exc:
        raise PolicyError(str(exc), 422) from exc
    if get_settings().serverless and model.provider == llm_service.OLLAMA_LOCAL:
        raise PolicyError(
            "Local Ollama models are not available on this deployment; pick a hosted model.", 422
        )
    try:
        keys_service.credentials_for_provider(db, user_id, model.provider)
    except keys_service.KeyError as exc:
        raise PolicyError(exc.detail, exc.status_code) from exc
    try:
        foundation = skills_service.get_foundation(foundation_id)
    except skills_service.SkillError as exc:
        raise PolicyError(exc.detail, exc.status_code) from exc
    return model.id, foundation.id


def _clean_pattern(pattern: str) -> str:
    cleaned = (pattern or "").strip()
    if not cleaned:
        raise PolicyError("A repository pattern is required.", 422)
    if cleaned.count("/") > 1:
        raise PolicyError("Use `owner/repo` or a glob such as `owner/*`.", 422)
    return cleaned


def _clean_involvement(involvement: str) -> str:
    if involvement not in PolicyInvolvement.ALL:
        raise PolicyError(
            f"Unknown involvement: {involvement}. Use one of {', '.join(PolicyInvolvement.ALL)}.",
            422,
        )
    return involvement


def create_policy(
    db: Session,
    user_id: int,
    *,
    repo_pattern: str,
    involvement: str,
    model_id: str,
    skill_foundation: str | None = None,
    max_active: int = 1,
    enabled: bool = True,
) -> ReviewPolicy:
    model_used, foundation_id = _validate(db, user_id, model_id, skill_foundation)
    policy = ReviewPolicy(
        user_id=user_id,
        repo_pattern=_clean_pattern(repo_pattern),
        involvement=_clean_involvement(involvement),
        model_used=model_used,
        skill_foundation=foundation_id,
        max_active=max(1, min(int(max_active), 10)),
        enabled=bool(enabled),
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy


def update_policy(
    db: Session,
    policy: ReviewPolicy,
    *,
    repo_pattern: str | None = None,
    involvement: str | None = None,
    model_id: str | None = None,
    skill_foundation: str | None = None,
    max_active: int | None = None,
    enabled: bool | None = None,
) -> ReviewPolicy:
    if repo_pattern is not None:
        policy.repo_pattern = _clean_pattern(repo_pattern)
    if involvement is not None:
        policy.involvement = _clean_involvement(involvement)
    if model_id is not None or skill_foundation is not None:
        # Re-validate the pair together: a model key removed since creation must fail here,
        # not silently on every tick.
        model_used, foundation_id = _validate(
            db,
            policy.user_id,
            model_id if model_id is not None else policy.model_used,
            skill_foundation if skill_foundation is not None else policy.skill_foundation,
        )
        policy.model_used = model_used
        policy.skill_foundation = foundation_id
    if max_active is not None:
        policy.max_active = max(1, min(int(max_active), 10))
    if enabled is not None:
        policy.enabled = bool(enabled)
    policy.last_error = None
    db.commit()
    db.refresh(policy)
    return policy


def delete_policy(db: Session, policy: ReviewPolicy) -> None:
    db.delete(policy)
    db.commit()


def _matches(policy: ReviewPolicy, row: CachedPR) -> bool:
    repo = f"{row.repo_owner}/{row.repo_name}".lower()
    if not fnmatch.fnmatchcase(repo, policy.repo_pattern.strip().lower()):
        return False
    if policy.involvement == PolicyInvolvement.ANY:
        return True
    return row.involvement == policy.involvement


async def evaluate(max_reviews: int | None = None) -> PolicyTickResult:
    """One pass over every enabled policy; at most `max_reviews` starts across all of them."""
    config = get_settings()
    budget = config.policy_max_reviews_per_tick if max_reviews is None else max_reviews
    result = PolicyTickResult()

    policy_ids = _due_policy_ids()
    for index, policy_id in enumerate(policy_ids):
        if len(result.started) >= budget:
            result.skipped += len(policy_ids) - index
            break
        try:
            started, skipped, error = await _evaluate_policy(policy_id, budget - len(result.started))
        except Exception as exc:  # noqa: BLE001 - one broken policy must not stop the tick
            logger.exception("Policy %s could not be evaluated", policy_id)
            result.failed.append({"policy_id": policy_id, "error": type(exc).__name__})
            continue
        result.started.extend(started)
        result.skipped += skipped
        if error is not None:
            result.failed.append({"policy_id": policy_id, "error": error})
    return result


async def _evaluate_policy(policy_id: int, budget: int) -> tuple[list[int], int, str | None]:
    """Start up to `budget` reviews for one policy. Returns `(ids, skipped, first_error)`."""
    # Imported here, not at module scope: `review_pipeline` imports `thread_sync`, which imports
    # `apply_service`, which imports `review_pipeline` back — the route module loads earlier than
    # that cycle finishes, so a top-level import is an ImportError at collection time.
    from app.services.review_pipeline import PipelineError, create_running_review, run_ingest

    config = get_settings()
    started: list[int] = []
    skipped = 0
    first_error: str | None = None

    with SessionLocal() as db:
        policy = db.get(ReviewPolicy, policy_id)
        if policy is None or not policy.enabled:
            return [], 0, None

        rows = list(
            db.scalars(
                select(CachedPR)
                .where(
                    CachedPR.user_id == policy.user_id,
                    CachedPR.linked_review_id.is_(None),
                    CachedPR.status == InboxStatus.NEEDS_REVIEW,
                )
                .order_by(CachedPR.last_github_activity_at.desc(), CachedPR.id.desc())
            )
        )
        candidates = [row for row in rows if _matches(policy, row)]
        if not candidates:
            _mark_run(db, policy)
            return [], 0, None

        active = db.scalar(
            select(func.count())
            .select_from(CodeReview)
            .where(CodeReview.policy_id == policy.id, CodeReview.status.in_(ACTIVE_STATUSES))
        )
        room = max(0, policy.max_active - int(active or 0))
        if room == 0:
            _mark_run(db, policy)
            return [], len(candidates), None

        stale_before = utcnow() - timedelta(minutes=config.policy_claim_stale_minutes)
        for row in candidates:
            if len(started) >= budget or len(started) >= room:
                skipped += 1
                continue
            claimed = db.execute(
                update(CachedPR)
                .where(
                    CachedPR.id == row.id,
                    CachedPR.linked_review_id.is_(None),
                    or_(CachedPR.policy_claim_at.is_(None), CachedPR.policy_claim_at < stale_before),
                )
                .values(policy_claim_at=utcnow())
            ).rowcount
            if claimed != 1:
                skipped += 1  # another tick owns this PR
                continue
            db.commit()

            try:
                review = create_running_review(
                    db,
                    policy.user_id,
                    row.pr_url,
                    policy.model_used,
                    policy.skill_foundation,
                    trigger=ReviewTrigger.POLICY,
                    policy_id=policy.id,
                )
                review_id = review.id
                policy.last_run_at = utcnow()
                policy.last_error = None
                db.commit()
            except (PipelineError, PolicyError) as exc:
                db.rollback()
                detail = exc.detail
                first_error = first_error or detail
                _release_claim(db, row.id)
                _record_failure(db, policy, detail)
                continue
            except SQLAlchemyError:
                db.rollback()
                _release_claim(db, row.id)
                _record_failure(db, policy, "The review row could not be created.")
                first_error = first_error or "database error"
                continue

            started.append(review_id)
            # Ingest runs outside this session, like every other review.
            await run_ingest(review_id)

        _mark_run(db, policy, error=first_error)
    return started, skipped, first_error


def _release_claim(db: Session, cached_pr_id: int) -> None:
    """Let the next tick retry a PR whose review creation failed."""
    try:
        db.execute(
            update(CachedPR).where(CachedPR.id == cached_pr_id).values(policy_claim_at=None)
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.warning("Could not release the policy claim on cached PR %s", cached_pr_id)


def _mark_run(db: Session, policy: ReviewPolicy, *, error: str | None = None) -> None:
    """Move the policy to the back of the queue even when nothing matched.

    Without this, a policy whose glob matches nothing would stay the never-run row at the head of
    every tick and starve the others.
    """
    try:
        policy.last_run_at = utcnow()
        if error is None:
            policy.last_error = None
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.warning("Could not record the policy run for %s", policy.id)


def _record_failure(db: Session, policy: ReviewPolicy, detail: str) -> None:
    """Store the first line only — never a prompt, a diff or a credential."""
    message = " ".join((detail or "").splitlines())[:MAX_ERROR_CHARS] or "Unknown error"
    policy.last_error = message
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.warning("Could not record the policy failure for %s", policy.id)


def _due_policy_ids() -> list[int]:
    """Enabled policies, never-run first, then oldest run. Both engines agree on this order."""
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(ReviewPolicy.id)
                .where(ReviewPolicy.enabled.is_(True))
                .order_by(
                    ReviewPolicy.last_run_at.is_(None).desc(),
                    ReviewPolicy.last_run_at.asc(),
                    ReviewPolicy.id.asc(),
                )
            )
        )
