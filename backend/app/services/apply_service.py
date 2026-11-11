"""Publish the reviewed thread state to GitHub or GitLab.

Two kinds of work go out in one call, and only what is pending:

1. **Initial findings** — AI threads whose Round 1 was never posted. They travel as one formal
   review with inline comments, and the resulting per-thread comment ids are backfilled so later
   replies can be threaded.
2. **Replies** — every round the reviewer marked `pending_apply`. Each is posted into its own
   GitHub thread with `POST …/comments/{id}/replies`.

Rounds marked `resolved_no_reply` are never posted. Applying again after everything went out is a
`409`, not a duplicate post.

An `APPROVE` with nothing pending is the one exception to "nothing to publish is an error": it goes
out as an approval with no inline comments, the same review the GitHub UI submits.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.review import (
    CodeReview,
    MessageRole,
    ReviewStatus,
    ReviewThread,
    RoundStatus,
    ThreadOrigin,
    ThreadRound,
    ThreadStatus,
)
from app.schemas.review import ApplyRequest
from app.services import github_service, keys_service, thread_sync, vcs
from app.services.diff_parser import parse_diff, reviewable_files, resolve_path
from app.services.github_service import GitHubError
from app.services.review_pipeline import PipelineError
from app.services.summarise import summarise_round, summarise_threads
from app.services.vcs import VCSError

logger = logging.getLogger(__name__)

__all__ = [
    "apply_review",
    "build_comments",
    "collate_comments",
    "decide_round",
    "pending_round_count",
    "recompute_status",
    "revalidate_anchors",
]


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _select_threads(review: CodeReview, thread_ids: list[int] | None) -> list[ReviewThread]:
    threads = list(review.threads)
    if thread_ids is None:
        return threads
    wanted = set(thread_ids)
    unknown = wanted - {thread.id for thread in threads}
    if unknown:
        raise PipelineError(f"Thread {sorted(unknown)[0]} does not belong to this review.", 400)
    return [thread for thread in threads if thread.id in wanted]


def _last_assistant_text(thread: ReviewThread, round_number: int | None = None) -> str:
    for message in reversed(thread.messages):
        if message.role != MessageRole.ASSISTANT:
            continue
        if round_number is not None and (message.round_number or 1) != round_number:
            continue
        return message.content.strip()
    return ""


def _initial_threads(threads: list[ReviewThread]) -> list[ReviewThread]:
    """AI findings whose first round the reviewer accepted and nobody published yet."""
    selected: list[ReviewThread] = []
    for thread in threads:
        first = thread.round(1)
        if (
            thread.origin == ThreadOrigin.AI_GENERATED
            and not thread.dropped
            and first is not None
            and first.status == RoundStatus.PENDING_APPLY
        ):
            selected.append(thread)
    return selected


def _reply_rounds(threads: list[ReviewThread]) -> list[tuple[ReviewThread, ThreadRound]]:
    """Rounds explicitly marked ready, excluding the initial findings handled as a review."""
    selected: list[tuple[ReviewThread, ThreadRound]] = []
    for thread in threads:
        for item in thread.rounds:
            if item.status != RoundStatus.PENDING_APPLY:
                continue
            if thread.origin == ThreadOrigin.AI_GENERATED and item.round_number == 1:
                continue
            selected.append((thread, item))
    return selected


def pending_round_count(review: CodeReview) -> int:
    """Everything the apply button has work for: unposted findings plus ready replies."""
    threads = list(review.threads)
    return len(_initial_threads(threads)) + len(_reply_rounds(threads))


def _has_published_content(review: CodeReview) -> bool:
    """True once round 1 of any AI finding is published or the review has a GitHub review URL."""
    if review.github_review_url:
        return True
    for thread in review.threads:
        if thread.origin != ThreadOrigin.AI_GENERATED:
            continue
        first = thread.round(1)
        if first is not None and first.status == RoundStatus.PUBLISHED:
            return True
    return False


def _has_approval_only(review: CodeReview) -> bool:
    """True when the review has a github_review_url but no AI findings were published as comments."""
    if not review.github_review_url:
        return False
    for thread in review.threads:
        if thread.origin != ThreadOrigin.AI_GENERATED:
            continue
        first = thread.round(1)
        if first is not None and first.status == RoundStatus.PUBLISHED:
            return False
    return True


def _has_open_reply_round(review: CodeReview) -> bool:
    """True when any thread has a drafting round beyond round 1 (active discussion)."""
    for thread in review.threads:
        for item in thread.rounds:
            if item.round_number > 1 and item.status == RoundStatus.DRAFTING:
                return True
    return False


def recompute_status(review: CodeReview) -> str:
    """Derive the review-level status from the current thread/round state.

    A review is in discussion once the reviewer has accepted at least one finding, opened a
    reply round, or has an open drafting round beyond round 1, even if nothing is published
    yet. It is applied once its findings (or an approval with no inline comments) were published
    to GitHub, even if later discussion rounds are still open.
    """
    if pending_round_count(review) > 0:
        if review.github_review_url or _has_published_content(review):
            return ReviewStatus.IN_DISCUSSION
        return ReviewStatus.DRAFT
    if _has_published_content(review) or _has_approval_only(review):
        return ReviewStatus.APPLIED
    if _has_accepted_finding(review) or _has_open_reply_round(review):
        return ReviewStatus.IN_DISCUSSION
    return ReviewStatus.DRAFT


def _has_accepted_finding(review: CodeReview) -> bool:
    """True when an AI round 1 was accepted (pending_apply) but not yet published."""
    for thread in review.threads:
        if thread.origin != ThreadOrigin.AI_GENERATED:
            continue
        first = thread.round(1)
        if first is not None and first.status == RoundStatus.PENDING_APPLY:
            return True
    return False


def collate_comments(review: CodeReview, threads: list[ReviewThread]) -> tuple[list[dict], list[str]]:
    """One inline comment per thread, built from the agreed conclusion."""
    warnings: list[str] = []

    comments: list[dict] = []
    for thread in threads:
        assistant = [m for m in thread.messages if m.role == MessageRole.ASSISTANT]
        if not assistant:
            warnings.append(f"Skipped thread {thread.id}: it has no assistant message to export.")
            continue
        conclusion = assistant[-1].content.strip()
        if len(thread.messages) > 1:
            conclusion = f"**AI Review Conclusion:** {conclusion}"
        if thread.messages[-1].role == MessageRole.USER:
            warnings.append(
                f"Thread {thread.id} ends with an unanswered reviewer question; the last AI "
                "conclusion was exported."
            )
        comments.append(
            {
                "path": thread.file_path,
                "line": thread.line_number,
                "side": "RIGHT",
                "body": conclusion,
            }
        )
    return comments, warnings


async def build_comments(
    db: Session, review: CodeReview, threads: list[ReviewThread]
) -> tuple[list[dict], list[str], bool, list[int]]:
    """Summarise + prune, falling back to deterministic collation if the pass is unusable."""
    outcome = await summarise_threads(db, review, threads)

    if outcome is None:
        comments, warnings = collate_comments(review, threads)
        warnings.append(
            "Summarisation was unavailable, so each comment uses the last message of its thread."
        )
        return comments, warnings, False, []

    warnings = list(outcome.warnings)
    comments: list[dict] = []
    for thread in threads:
        if thread.id in outcome.dropped:
            continue
        body = outcome.summaries.get(thread.id) or _last_assistant_text(thread)
        if not body:
            warnings.append(f"Skipped thread {thread.id}: nothing to export.")
            continue
        comments.append(
            {
                "path": thread.file_path,
                "line": thread.line_number,
                "side": "RIGHT",
                "body": body,
            }
        )
    return comments, warnings, True, sorted(outcome.dropped)


async def revalidate_anchors(
    key, ref: "vcs.PullRef", comments: list[dict]
) -> tuple[list[dict], list[str]]:
    """Drop comments whose file/line no longer exists on the current diff.

    GitHub rejects the entire review if any single inline comment is anchored outside the diff,
    and GitLab 400s an invalid position. The branch may have moved since ingest.
    """
    try:
        diff_text = await vcs.fetch_diff(key, ref)
    except VCSError as exc:
        raise PipelineError(f"Could not re-read the change diff: {exc.message}", 502) from exc

    files = reviewable_files(parse_diff(diff_text))
    kept: list[dict] = []
    warnings: list[str] = []
    for comment in comments:
        target = resolve_path(files, comment["path"])
        if target is None:
            warnings.append(
                f"Dropped comment on {comment['path']}:{comment['line']} — the file is no longer in the diff."
            )
            continue
        if comment["line"] not in target.right_lines():
            warnings.append(
                f"Dropped comment on {comment['path']}:{comment['line']} — that line is no longer "
                "part of the diff (the branch moved)."
            )
            continue
        kept.append(comment)
    return kept, warnings


async def _backfill_root_ids(
    review: CodeReview,
    key,
    ref: "vcs.PullRef",
    published: dict,
    threads: list[ReviewThread],
    warnings: list[str],
) -> None:
    """Map each posted finding back to its GitHub comment id, so replies can be threaded."""
    review_id = _as_int(published.get("review_id"))
    if review_id is None:
        return
    try:
        comments = await github_service.fetch_review_id_comments(
            key.token, ref.project, ref.number, review_id, base_url=vcs.api_base(key, ref)
        )
    except GitHubError as exc:
        warnings.append(
            f"Posted the review, but could not read its comment ids ({exc.message}); "
            "replies to these findings cannot be threaded until the next sync."
        )
        return

    by_body: dict[str, dict] = {}
    by_anchor: dict[tuple[str, int], list[dict]] = {}
    for comment in comments:
        comment_id = _as_int(comment.get("id"))
        if comment_id is None:
            continue
        body = comment.get("body")
        if isinstance(body, str) and body.strip():
            by_body.setdefault(thread_sync.body_key(body), comment)
        path = comment.get("path")
        line = _as_int(comment.get("line")) or _as_int(comment.get("original_line"))
        if isinstance(path, str) and line is not None:
            by_anchor.setdefault((path, line), []).append(comment)

    missing = 0
    for thread in threads:
        wanted = thread_sync.body_key(thread.summary or _last_assistant_text(thread))
        candidates = by_anchor.get((thread.file_path, thread.line_number), [])
        # Anchor + text is exact; text alone survives a payload without `line` (the old
        # review-scoped endpoint); a lone anchor is the last resort.
        chosen = next(
            (item for item in candidates if thread_sync.body_key(item.get("body")) == wanted),
            None,
        )
        if chosen is None:
            chosen = by_body.get(wanted)
        if chosen is None and candidates:
            chosen = candidates[0]
        if chosen is None:
            missing += 1
            continue
        thread.github_root_comment_id = _as_int(chosen.get("id"))
        if thread.github_root_comment_id is None:
            missing += 1
            continue
        first = thread.round(1)
        if first is not None and not first.published_github_comment_id:
            first.published_github_comment_id = thread.github_root_comment_id

    if missing:
        warnings.append(
            f"{missing} finding(s) could not be matched to a GitHub comment id; their replies "
            "will not be threaded."
        )


ACCEPT = "accept"
PUSH_BACK = "push_back"
_DECISION_ALIASES = {"publish": ACCEPT, "resolve": PUSH_BACK}


async def decide_round(
    db: Session,
    review: CodeReview,
    round_id: int,
    decision: str,
    summary: str | None = None,
) -> tuple[CodeReview, list[str]]:
    """Accept a round (summarise it into the comment to publish) or push it back (publish nothing).

    `accept` without `summary` runs one model pass over the thread and the round and stores the
    result as the text to publish; `accept` with `summary` stores the reviewer's wording verbatim.
    """
    decision = _DECISION_ALIASES.get(decision, decision)
    if decision not in (ACCEPT, PUSH_BACK):
        raise PipelineError("Unknown decision; use 'accept' or 'push_back'.", 422)

    thread: ReviewThread | None = None
    item: ThreadRound | None = None
    for candidate in review.threads:
        for round_row in candidate.rounds:
            if round_row.id == round_id:
                thread, item = candidate, round_row
                break
        if item is not None:
            break
    if thread is None or item is None:
        raise PipelineError("That round does not belong to this review.", 404)
    if item.status == RoundStatus.PUBLISHED:
        raise PipelineError(
            "This round is already on GitHub; a posted comment cannot be withdrawn.", 409
        )

    warnings: list[str] = []
    if decision == ACCEPT:
        text = (summary or "").strip()
        if not text:
            generated, warnings = await summarise_round(db, review, thread, item)
            text = (generated or _last_assistant_text(thread, item.round_number)).strip()
        if not text:
            raise PipelineError(
                "There is nothing to publish yet: ask the copilot for a reply or write one.", 422
            )
        item.final_summary = text
        item.status = RoundStatus.PENDING_APPLY
        if thread.origin == ThreadOrigin.AI_GENERATED and item.round_number == 1:
            # Accepting a finding again clears an earlier withdrawal.
            thread.dropped = False
        thread.thread_status = (
            ThreadStatus.NEEDS_RESPONSE if item.inbound_github_comment_id else ThreadStatus.ACTIVE
        )
    else:
        if summary and summary.strip():
            item.final_summary = summary.strip()
        item.status = RoundStatus.RESOLVED_NO_REPLY
        thread.thread_status = ThreadStatus.RESOLVED
        if thread.origin == ThreadOrigin.AI_GENERATED and item.round_number == 1:
            # Pushing back a finding withdraws it: no comment, and the verdict prompt knows.
            thread.dropped = True

    review.status = recompute_status(review)
    db.commit()
    db.refresh(review)
    return review, warnings


async def apply_review(
    db: Session, review: CodeReview, payload: ApplyRequest
) -> tuple[CodeReview, dict, list[str]]:
    try:
        ref = vcs.parse_pr_url(review.pr_url)
    except VCSError as exc:
        raise PipelineError(exc.message, 422) from exc

    key = keys_service.version_control_for(db, review.user_id, ref.vcs)
    if key is None:
        raise PipelineError(keys_service.missing_vcs_message(ref.vcs), 400)
    if not review.commit_id:
        raise PipelineError(
            "This review has no recorded HEAD commit, so comments cannot be anchored.", 422
        )
    if not review.repo_full_name or not review.pr_number:
        raise PipelineError("This review is not linked to a pull request.", 422)

    selected = _select_threads(review, payload.thread_ids)
    initial = _initial_threads(selected)
    replies = _reply_rounds(selected)
    # An approval is the one outcome that needs nothing to say: the PR itself is the message. It
    # only applies when there is nothing else to publish — a run with queued replies keeps its
    # existing behaviour of posting the replies without a review.
    approval_only = payload.event == "APPROVE" and not initial and not replies

    if not initial and not replies:
        if review.status == ReviewStatus.APPLIED:
            raise PipelineError("Nothing is pending: everything in this review is already on GitHub.", 409)
        if not approval_only:
            raise PipelineError(
                "Nothing is accepted yet: accept the findings you want to publish, then apply again.",
                400,
            )

    warnings: list[str] = []
    summarised = False
    dropped: list[int] = []
    comments_posted = 0
    replies_posted = 0
    review_url: str | None = None

    comments: list[dict] = []
    if initial:
        # An accepted round is published exactly as the reviewer approved it; only threads without
        # an accepted text go through the summarise-and-collate fallback.
        accepted: list[tuple[ReviewThread, str]] = []
        without_summary: list[ReviewThread] = []
        for thread in initial:
            first_round = thread.round(1)
            text = (first_round.final_summary or "").strip() if first_round else ""
            if text:
                accepted.append((thread, text))
            else:
                without_summary.append(thread)

        build_warnings: list[str] = []
        if without_summary:
            generated, build_warnings, summarised, dropped = await build_comments(
                db, review, without_summary
            )
            comments.extend(generated)
        comments.extend(
            {
                "path": thread.file_path,
                "line": thread.line_number,
                "side": "RIGHT",
                "body": text,
            }
            for thread, text in accepted
        )
        warnings.extend(build_warnings)
        comments, stale_warnings = await revalidate_anchors(key, ref, comments)
        warnings.extend(stale_warnings)
        if not comments:
            raise PipelineError(
                "Nothing to publish: every accepted finding was withdrawn or no longer matches the "
                "diff. Review the findings and apply again.",
                422,
            )

    if initial or approval_only:
        # `comments` is empty only for an approval with nothing accepted: GitHub accepts that as a
        # plain approval and GitLab records an approval without a discussion.
        try:
            pull = await vcs.fetch(key, ref)
            published, publish_warnings = await vcs.publish(
                key, ref, pull, event=payload.event, comments=comments
            )
        except VCSError as exc:
            raise PipelineError(exc.message, 502) from exc
        warnings.extend(publish_warnings)

        comments_posted = published.get("comments_posted", 0)
        review_url = published.get("url")

        if initial:
            await _backfill_root_ids(review, key, ref, published, initial, warnings)

            for thread in initial:
                first = thread.round(1)
                if first is None:
                    continue
                if thread.dropped:
                    first.status = RoundStatus.RESOLVED_NO_REPLY
                    thread.thread_status = ThreadStatus.RESOLVED
                    continue
                first.status = RoundStatus.PUBLISHED
                if not first.final_summary:
                    first.final_summary = thread.summary or _last_assistant_text(thread)
                thread.thread_status = ThreadStatus.APPLIED

            # Summarisation may have withdrawn a thread not in the selection's dropped list.
            for thread in initial:
                if thread.dropped and thread.id not in dropped:
                    dropped.append(thread.id)

    for thread, item in replies:
        text = (item.final_summary or _last_assistant_text(thread, item.round_number)).strip()
        if not text:
            warnings.append(
                f"Round {item.round_number} of thread {thread.id} has no agreed text to post."
            )
            continue
        if not thread.github_root_comment_id:
            warnings.append(
                f"Round {item.round_number} of thread {thread.id} cannot be posted: its GitHub "
                "comment id is unknown."
            )
            continue
        try:
            posted = await vcs.post_reply(key, ref, thread.github_root_comment_id, text)
        except VCSError as exc:
            warnings.append(
                f"Round {item.round_number} of thread {thread.id} was not posted: {exc.message}"
            )
            continue
        item.final_summary = text
        item.status = RoundStatus.PUBLISHED
        item.published_github_comment_id = _as_int(posted.get("id"))
        thread.thread_status = ThreadStatus.APPLIED
        replies_posted += 1

    review.status = recompute_status(review)
    review.verdict = payload.event
    if review_url:
        review.github_review_url = review_url
    # Recompute again after setting the URL, so an approval with no inline comments still lands applied.
    review.status = recompute_status(review)
    db.commit()
    db.refresh(review)

    return review, {
        "github_review_url": review.github_review_url,
        "comments_posted": comments_posted,
        "replies_posted": replies_posted,
        "summarised": summarised,
        "dropped": sorted(dropped),
    }, warnings
