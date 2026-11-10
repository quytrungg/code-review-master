"""Ingestion → skill injection → model call → anchored findings → persistence.

The pipeline runs as a background job so the API can return immediately and stream progress.
`create_running_review` performs every cheap validation that should still be a 4xx on the
request; everything that needs the network happens inside `run_ingest` and reports failures
as `failed` status plus an SSE `error` event.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.review import (
    CodeReview,
    MessageRole,
    ReviewStatus,
    ReviewThread,
    RoundStatus,
    ThreadMessage,
    ThreadOrigin,
    ThreadRound,
    ThreadStatus,
)
from app.schemas.review import RawFinding
from app.services import (
    keys_service,
    llm_service,
    prompts,
    skill_loader,
    skills_service,
    thread_sync,
    vcs,
)
from app.services.diff_parser import (
    anchor_line,
    language_hints,
    parse_diff,
    rebuild_snippet,
    resolve_path,
    reviewable_files,
    snippet_contains_line,
)
from app.models.llm_call import LLMPurpose
from app.services.llm_service import LLMError
from app.services.progress import ERROR as PROGRESS_ERROR
from app.services.progress import WARN as PROGRESS_WARN
from app.services.progress import bus
from app.services.settings_service import get_or_create
from app.services.skills_service import SkillError

logger = logging.getLogger(__name__)

# Keep a reference so the event loop does not garbage-collect a running ingest task.
_tasks: set[asyncio.Task] = set()


class PipelineError(Exception):
    def __init__(self, detail: str, status_code: int = 400, review_id: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.review_id = review_id


class BackgroundScheduler(Protocol):
    """The part of Starlette's `BackgroundTasks` the pipeline uses.

    Typed structurally so the service layer never imports FastAPI (AGENTS §5); the route passes
    the framework object, which satisfies this protocol.
    """

    def add_task(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None: ...


@dataclass
class AnchoredFinding:
    path: str
    line_number: int
    diff_hunk: str
    comment: str


def anchor_findings(findings: list[RawFinding], files, warnings: list[str]) -> list[AnchoredFinding]:
    anchored: list[AnchoredFinding] = []
    for finding in findings:
        target = resolve_path(files, finding.file_path)
        if target is None:
            warnings.append(f"Dropped a finding for a file that is not in the diff: {finding.file_path}")
            continue

        line_number = anchor_line(target, finding.line_number)
        if line_number is None:
            warnings.append(
                f"Dropped a finding on {target.path}:{finding.line_number} — the file has no commented side."
            )
            continue

        line = target.right_lines()[line_number]
        # Prefer the hunk rebuilt from the real diff: it carries surrounding context and is
        # guaranteed to contain the anchored line. The model's own quote is the fallback.
        rebuilt = rebuild_snippet(target, line_number)
        if rebuilt and snippet_contains_line(rebuilt, line.text):
            hunk = rebuilt
        elif snippet_contains_line(finding.diff_hunk, line.text):
            hunk = finding.diff_hunk.strip()
        else:
            hunk = rebuilt or finding.diff_hunk.strip()
        anchored.append(
            AnchoredFinding(
                path=target.path,
                line_number=line_number,
                diff_hunk=hunk,
                comment=finding.initial_comment,
            )
        )
    return anchored


def create_running_review(
    db: Session,
    user_id: int,
    pr_url: str,
    model_id: str,
    skill_foundation: str | None = None,
) -> CodeReview:
    """Validate the request and persist a `running` review row; no network calls."""
    try:
        ref = vcs.parse_pr_url(pr_url)
    except vcs.VCSError as exc:
        raise PipelineError(exc.message, 400) from exc

    key = keys_service.version_control_for(db, user_id, ref.vcs)
    if key is None:
        raise PipelineError(keys_service.missing_vcs_message(ref.vcs), 400)

    try:
        model = llm_service.parse_model_id(model_id)
    except LLMError as exc:
        raise PipelineError(str(exc), 422) from exc
    if get_settings().serverless and model.provider == llm_service.OLLAMA_LOCAL:
        # A deployed function cannot reach the operator's local daemon, and silently failing
        # 20 seconds later is worse than refusing the request.
        raise PipelineError(
            "Local Ollama models are not available on this deployment; pick a hosted model.", 422
        )
    try:
        keys_service.credentials_for_provider(db, user_id, model.provider)
    except keys_service.KeyError as exc:
        raise PipelineError(exc.detail, exc.status_code) from exc

    try:
        foundation = skills_service.get_foundation(skill_foundation)
    except SkillError as exc:
        raise PipelineError(exc.detail, exc.status_code) from exc

    review = CodeReview(
        user_id=user_id,
        pr_url=pr_url.strip(),
        vcs=ref.vcs,
        model_used=model.id,
        skill_foundation=foundation.id,
        status=ReviewStatus.RUNNING,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    bus.publish(
        review.id,
        "queued",
        "Queued",
        detail=f"{ref.label} · {model.id} · foundation {foundation.id}",
        progress=2,
    )
    return review


def schedule_ingest(review_id: int, background: BackgroundScheduler | None = None) -> None:
    """Start `run_ingest` for a freshly created review.

    A serverless function is torn down when its ASGI call completes, which cancels a bare
    `asyncio.create_task`; the deployed runtime keeps the invocation alive for Starlette's
    background tasks (Vercel's FastAPI background-task support), so serverless mode hands the job
    to the response instead. The `vercel` SDK's `wait_until` is the fallback if a preview deploy
    shows the task is cut, but it drags a dozen packages and a pydantic bump into the image for
    one helper.
    """
    if get_settings().serverless and background is not None:
        background.add_task(run_ingest, review_id)
        return

    task = asyncio.create_task(run_ingest(review_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def run_ingest(review_id: int) -> None:
    db = SessionLocal()
    try:
        review = db.get(CodeReview, review_id)
        if review is None or review.status != ReviewStatus.RUNNING:
            return
        try:
            await execute(db, review)
        except Exception as exc:  # noqa: BLE001 - a crash must never leave the review `running`
            db.rollback()
            logger.exception("Ingest crashed for review %s", review_id)
            _fail(db, review, f"Review failed unexpectedly: {_short_error(exc)}")
    finally:
        db.close()


def _short_error(exc: BaseException) -> str:
    """The first line of an unexpected exception, bounded.

    SQLAlchemy puts SQL parameters (comment bodies, addresses) on later lines, so keeping only the
    first one names the cause in `code_reviews.error` without copying prompt data into the database.
    """
    text = str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__
    return text[:200]


def _fail(db: Session, review: CodeReview, detail: str) -> None:
    review.status = ReviewStatus.FAILED
    review.error = detail
    db.commit()
    try:
        bus.publish(
            review.id, "error", "Review failed", detail=detail, level=PROGRESS_ERROR, terminal=True
        )
    except Exception:  # noqa: BLE001 - a broken progress store must not mask the real cause
        logger.warning("Could not publish the failure event for review %s", review.id)
    logger.warning("Ingest failed for review %s: %s", review.id, detail)


async def execute(db: Session, review: CodeReview) -> list[str]:
    """Run the pipeline for an existing `running` review. Never raises for expected failures."""
    config = get_settings()
    warnings: list[str] = []
    settings_row = get_or_create(db, review.user_id)
    bus.publish(review.id, "fetch_pr", "Fetching pull request", detail=review.pr_url, progress=8)

    try:
        ref = vcs.parse_pr_url(review.pr_url)
        key = keys_service.version_control_for(db, review.user_id, ref.vcs)
        if key is None:
            raise vcs.VCSError(keys_service.missing_vcs_message(ref.vcs), 400)
        pr = await vcs.fetch(key, ref)
        # Persist the identity immediately so the header is informative while the job runs.
        review.pr_url = pr.html_url
        review.pr_title = pr.title
        review.pr_number = pr.number
        review.repo_full_name = pr.project
        review.vcs = pr.vcs
        review.commit_id = pr.head_sha
        db.commit()
        bus.publish(
            review.id,
            "fetch_pr",
            "Pull request fetched",
            detail=f"{pr.project}{'#' if pr.vcs == 'github' else '!'}{pr.number} · “{pr.title}”",
            progress=18,
        )

        bus.publish(review.id, "fetch_diff", "Reading the diff", progress=24)
        diff_text = await vcs.fetch_diff(key, ref)
        bus.publish(
            review.id,
            "fetch_diff",
            "Diff received",
            detail=f"{len(diff_text):,} characters",
            progress=30,
        )
    except vcs.VCSError as exc:
        _fail(db, review, exc.message)
        return warnings

    all_files = parse_diff(diff_text)
    files = reviewable_files(all_files)
    skipped = [item.path for item in all_files if item.skipped_reason]
    bus.publish(
        review.id,
        "parse_diff",
        "Parsing changes",
        detail=f"{len(files)} reviewable file(s), {len(skipped)} skipped",
        progress=36,
    )
    if not files:
        _fail(db, review, "This pull request has no reviewable text changes.")
        return warnings
    if skipped:
        warnings.append(
            f"Skipped {len(skipped)} generated/vendored file(s): {', '.join(skipped[:5])}"
        )

    # Existing review comments are imported before the model runs: both kinds of thread are
    # first-class from the moment the workspace opens.
    imported = 0
    if review.vcs == "github":
        try:
            existing = await vcs.fetch_comments(key, ref)
            imported = thread_sync.ingest_existing_threads(
                db, review, thread_sync.group_comments(existing)
            )
            db.commit()
        except vcs.VCSError as exc:
            warnings.append(f"Existing PR comments could not be read: {exc.message}")
        bus.publish(
            review.id,
            "fetch_comments",
            "Reading existing comments",
            detail=(
                f"{imported} existing thread(s) imported"
                if imported
                else "No existing comments on this pull request"
            ),
            progress=40,
        )

    try:
        foundation = skills_service.get_foundation(review.skill_foundation)
    except SkillError:
        foundation = skills_service.get_foundation(None)
        warnings.append(
            f"Foundation '{review.skill_foundation}' is gone; fell back to {foundation.id}."
        )
    bundle = skill_loader.load_bundle(language_hints(files), root=foundation.path)
    if not bundle.included:
        warnings.append("No local skill files were found; the model used general review standards.")
    elif bundle.skipped:
        warnings.append(
            f"Prompt budget kept {len(bundle.included)} skill file(s); {len(bundle.skipped)} were left out."
        )
    bus.publish(
        review.id,
        "skills",
        "Reading skill files",
        detail=(
            f"{len(bundle.included)} of {max(len(foundation.files), len(bundle.included))} "
            f"file(s) from {foundation.id}"
        ),
        progress=45,
    )

    system_prompt = prompts.build_system_prompt(bundle.text)
    user_prompt, truncated = prompts.build_user_prompt(pr, files, config.diff_max_chars)
    if truncated:
        warnings.append("The diff was truncated to fit the model context.")
    bus.publish(
        review.id,
        "prompt",
        "Building the prompt",
        detail=f"{len(system_prompt) + len(user_prompt):,} characters",
        progress=50,
    )

    model = llm_service.parse_model_id(review.model_used or "")
    bus.publish(
        review.id,
        "model",
        f"Asking {model.name}",
        detail="Waiting for the model to return findings…",
        progress=55,
    )
    try:
        credentials = keys_service.credentials_for_provider(db, review.user_id, model.provider)
        outcome = await llm_service.generate(
            credentials,
            model,
            system_prompt,
            user_prompt,
            json_mode=True,
            purpose=LLMPurpose.INGEST,
            review_id=review.id,
        )
        result = llm_service.extract_review_result(outcome.text)
        payload = result.findings
    except keys_service.KeyError as exc:
        _fail(db, review, exc.detail)
        return warnings
    except LLMError as exc:
        _fail(db, review, str(exc))
        return warnings

    review.suggested_verdict = result.verdict
    review.confidence_percentage = result.confidence

    # Keep the PR identity now that it is known, so the dashboard can show it.
    db.commit()

    bus.publish(
        review.id,
        "parse",
        "Parsing findings",
        detail=(
            f"{len(payload)} finding(s) returned"
            + (f" · verdict {result.verdict}" if result.verdict else "")
            + (f" ({result.confidence}%)" if result.confidence is not None else "")
        ),
        progress=80,
    )

    findings: list[RawFinding] = []
    for item in payload:
        try:
            findings.append(RawFinding.model_validate(item))
        except ValidationError as exc:
            warnings.append(f"Ignored a malformed finding: {exc.errors()[0].get('msg', 'invalid')}")

    anchored = anchor_findings(findings, files, warnings)
    bus.publish(
        review.id,
        "anchor",
        "Anchoring findings",
        detail=f"{len(anchored)} anchored, {len(findings) - len(anchored)} dropped",
        progress=88,
    )

    for item in anchored:
        # A thread's ordinal in the UI is its position, which is 1-based; keep that stable.
        thread = ReviewThread(
            review_id=review.id,
            file_path=item.path,
            line_number=item.line_number,
            diff_hunk=item.diff_hunk,
            side="RIGHT",
            origin=ThreadOrigin.AI_GENERATED,
            current_round=1,
            thread_status=ThreadStatus.ACTIVE,
        )
        thread.messages.append(
            ThreadMessage(role=MessageRole.ASSISTANT, content=item.comment, round_number=1)
        )
        # Undecided until the reviewer accepts it: apply ignores a drafting round.
        thread.rounds.append(ThreadRound(round_number=1, status=RoundStatus.DRAFTING))
        db.add(thread)

    review.notes = "\n".join(warnings) if warnings else None
    review.status = ReviewStatus.DRAFT
    db.commit()
    db.refresh(review)

    bus.publish(
        review.id,
        "persist",
        "Saving review",
        detail=f"{len(anchored)} finding(s) and {imported} imported thread(s) stored",
        progress=96,
    )
    for warning in warnings:
        bus.publish(review.id, "persist", "Note", detail=warning, level=PROGRESS_WARN, progress=96)
    bus.publish(
        review.id,
        "done",
        "Review ready",
        detail=(
            f"{len(anchored)} finding(s) and {imported} existing thread(s) to discuss"
            if imported
            else f"{len(anchored)} finding(s) to discuss"
        ),
        progress=100,
        terminal=True,
        data={
            "review_id": review.id,
            "status": review.status,
            "thread_count": len(review.threads),
        },
    )
    return warnings


async def ingest_and_review(
    db: Session, pr_url: str, model_id: str, skill_foundation: str | None = None
) -> tuple[CodeReview, list[str]]:
    """Create and run a review inline (tests, scripts). Raises `PipelineError` on failure."""
    review = create_running_review(db, pr_url, model_id, skill_foundation)
    warnings = await execute(db, review)
    if review.status == ReviewStatus.FAILED:
        raise PipelineError(review.error or "Review failed", 502, review.id)
    return review, warnings
