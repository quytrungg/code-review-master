"""Import and synchronise existing GitHub review threads.

A pull request's review comments are flat: every comment points at its parent with
`in_reply_to_id` and only the first comment of a conversation has none. This module turns that list
into threads rooted at the top-level comment, stores them next to the AI findings, and later appends
the comments that appeared since the last sync as new rounds.

Deduplication is by GitHub comment id, kept on `ThreadMessage.github_comment_id` (and on the root /
inbound / published ids of threads and rounds). That is what makes a sync idempotent.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.review import (
    CodeReview,
    MessageRole,
    ReviewThread,
    RoundStatus,
    ThreadMessage,
    ThreadOrigin,
    ThreadRound,
    ThreadStatus,
)
from app.services import vcs
from app.services.vcs import PullRef

__all__ = [
    "InboundComment",
    "InboundThread",
    "SyncResult",
    "backfill_roots_from_comments",
    "body_key",
    "group_comments",
    "ingest_existing_threads",
    "known_comment_ids",
    "new_existing_thread",
    "sync_review",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InboundComment:
    id: int
    author: str
    body: str
    created_at: datetime


@dataclass(frozen=True)
class InboundThread:
    root_id: int
    path: str
    line_number: int
    diff_hunk: str
    author: str
    body: str
    created_at: datetime
    replies: tuple[InboundComment, ...] = ()


@dataclass
class SyncResult:
    new_threads: int = 0
    new_rounds: int = 0
    warnings: list[str] = field(default_factory=list)


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def body_key(text: str | None) -> str:
    """Whitespace-normalised prefix used to recognise a comment by the text that was posted."""
    return " ".join((text or "").split())[:160]


def _own_review_id(review: CodeReview) -> int | None:
    """The id of the review this tool published, taken from `…#pullrequestreview-<id>`."""
    match = re.search(r"pullrequestreview-(\d+)", review.github_review_url or "")
    return int(match.group(1)) if match else None


def _last_assistant_text(thread: ReviewThread) -> str:
    for message in reversed(list(thread.messages)):
        if message.role == MessageRole.ASSISTANT:
            return message.content.strip()
    return ""


def backfill_roots_from_comments(
    review: CodeReview, comments: list[dict], review_id: int
) -> int:
    """Give AI threads that lost their root id the comment this review posted.

    The apply-time backfill can miss — GitHub's review-scoped endpoint reports no `line` for these
    comments — which leaves `github_root_comment_id` NULL and makes later replies unattachable. The
    text the tool posted is exact, and the review id narrows the candidates, so sync heals it here
    with the list it has already fetched.
    """
    posted: dict[str, dict] = {}
    for comment in comments:
        if comment.get("pull_request_review_id") != review_id:
            continue
        body = comment.get("body")
        if isinstance(body, str) and body.strip():
            posted.setdefault(body_key(body), comment)
    if not posted:
        return 0

    healed = 0
    for thread in review.threads:
        if thread.origin != ThreadOrigin.AI_GENERATED or thread.github_root_comment_id:
            continue
        wanted = body_key(thread.summary or _last_assistant_text(thread))
        comment = posted.get(wanted)
        comment_id = _as_int(comment.get("id")) if comment else None
        if comment_id is None:
            continue
        thread.github_root_comment_id = comment_id
        first = thread.round(1)
        if first is not None and not first.published_github_comment_id:
            first.published_github_comment_id = comment_id
        healed += 1
    if healed:
        logger.info("Recovered %s GitHub root comment id(s) for review %s", healed, review.id)
    return healed


def _author(comment: dict) -> str:
    user = comment.get("user")
    login = user.get("login") if isinstance(user, dict) else None
    return login or "unknown"


def _timestamp(comment: dict) -> datetime:
    raw = comment.get("created_at")
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _line_number(comment: dict) -> int:
    return _as_int(comment.get("line")) or _as_int(comment.get("original_line")) or 1


def _root_of(comment: dict, by_id: dict[int, dict]) -> dict:
    """Walk `in_reply_to_id` up to the top-most comment we can see."""
    seen: set[int] = set()
    current = comment
    while True:
        parent_id = _as_int(current.get("in_reply_to_id"))
        if parent_id is None or parent_id in seen:
            return current
        seen.add(parent_id)
        parent = by_id.get(parent_id)
        if parent is None:
            return current
        current = parent


def group_comments(comments: list[dict]) -> list[InboundThread]:
    """Group a flat PR comment list into threads, oldest comment first."""
    by_id = {
        comment_id: comment
        for comment in comments
        if (comment_id := _as_int(comment.get("id"))) is not None
    }
    replies: dict[int, list[dict]] = {}
    roots: list[dict] = []
    for comment in comments:
        if _as_int(comment.get("id")) is None:
            continue
        if _as_int(comment.get("in_reply_to_id")) is None:
            roots.append(comment)
            continue
        root = _root_of(comment, by_id)
        root_id = _as_int(root.get("id"))
        if root_id is None or root_id == _as_int(comment.get("id")):
            continue
        replies.setdefault(root_id, []).append(comment)

    threads: list[InboundThread] = []
    for root in sorted(roots, key=lambda item: _as_int(item.get("id")) or 0):
        root_id = _as_int(root.get("id"))
        path = root.get("path")
        if root_id is None or not isinstance(path, str) or not path:
            continue
        history = sorted(
            replies.get(root_id, []), key=lambda item: _as_int(item.get("id")) or 0
        )
        threads.append(
            InboundThread(
                root_id=root_id,
                path=path,
                line_number=_line_number(root),
                diff_hunk=root.get("diff_hunk") if isinstance(root.get("diff_hunk"), str) else "",
                author=_author(root),
                body=(root.get("body") or "").strip(),
                created_at=_timestamp(root),
                replies=tuple(
                    InboundComment(
                        id=_as_int(reply.get("id")) or 0,
                        author=_author(reply),
                        body=(reply.get("body") or "").strip(),
                        created_at=_timestamp(reply),
                    )
                    for reply in history
                ),
            )
        )
    return threads


def new_existing_thread(review_id: int, item: InboundThread) -> ReviewThread:
    """One imported conversation: thread + round 1 (already live on GitHub) + its messages."""
    thread = ReviewThread(
        review_id=review_id,
        file_path=item.path,
        line_number=item.line_number,
        diff_hunk=item.diff_hunk,
        side="RIGHT",
        origin=ThreadOrigin.GITHUB_EXISTING,
        github_root_comment_id=item.root_id,
        original_author=item.author,
        current_round=1,
        thread_status=ThreadStatus.ACTIVE,
    )
    thread.messages.append(
        ThreadMessage(
            role=MessageRole.USER,
            content=item.body or "(empty comment)",
            round_number=1,
            is_external=True,
            github_comment_id=item.root_id,
            author=item.author,
            created_at=item.created_at,
        )
    )
    for reply in item.replies:
        thread.messages.append(
            ThreadMessage(
                role=MessageRole.USER,
                content=reply.body or "(empty comment)",
                round_number=1,
                is_external=True,
                github_comment_id=reply.id or None,
                author=reply.author,
                created_at=reply.created_at,
            )
        )
    thread.rounds.append(
        ThreadRound(
            round_number=1,
            inbound_github_comment_id=item.root_id,
            inbound_author=item.author,
            inbound_body=item.body,
            status=RoundStatus.PUBLISHED,
        )
    )
    return thread


def ingest_existing_threads(
    db: Session, review: CodeReview, threads: list[InboundThread]
) -> int:
    """Store imported conversations. Existing roots are skipped, never duplicated."""
    known = known_comment_ids(review)
    created = 0
    for item in threads:
        if item.root_id in known:
            continue
        db.add(new_existing_thread(review.id, item))
        known.add(item.root_id)
        created += 1
    return created


def known_comment_ids(review: CodeReview) -> set[int]:
    """Every GitHub comment id this review has already seen or posted."""
    ids: set[int] = set()
    for thread in review.threads:
        if thread.github_root_comment_id:
            ids.add(thread.github_root_comment_id)
        for message in thread.messages:
            if message.github_comment_id:
                ids.add(message.github_comment_id)
        for item in thread.rounds:
            if item.inbound_github_comment_id:
                ids.add(item.inbound_github_comment_id)
            if item.published_github_comment_id:
                ids.add(item.published_github_comment_id)
    return ids


def _open_round(thread: ReviewThread, comment: dict, author: str) -> ThreadRound:
    """One inbound comment opens exactly one round, so the reply answers that message."""
    number = (thread.current_round or 1) + 1
    round_row = ThreadRound(
        round_number=number,
        inbound_github_comment_id=_as_int(comment.get("id")),
        inbound_author=author,
        inbound_body=(comment.get("body") or "").strip(),
        status=RoundStatus.DRAFTING,
    )
    thread.rounds.append(round_row)
    thread.messages.append(
        ThreadMessage(
            role=MessageRole.USER,
            content=(comment.get("body") or "").strip() or "(empty comment)",
            round_number=number,
            is_external=True,
            github_comment_id=_as_int(comment.get("id")),
            author=author,
            created_at=_timestamp(comment),
        )
    )
    thread.current_round = number
    thread.thread_status = ThreadStatus.NEEDS_RESPONSE
    return round_row


async def sync_review(
    db: Session, review: CodeReview, key, ref: PullRef
) -> SyncResult:
    """Pull the PR's comments and append whatever this review has not seen yet."""
    outcome = SyncResult()
    if ref.vcs != "github":
        outcome.warnings.append(
            "Syncing inbound discussions is available for GitHub reviews only; nothing was fetched."
        )
        return outcome

    comments = await vcs.fetch_comments(key, ref)
    own_review_id = _own_review_id(review)
    if own_review_id is not None:
        backfill_roots_from_comments(review, comments, own_review_id)
    by_id = {
        comment_id: comment
        for comment in comments
        if (comment_id := _as_int(comment.get("id"))) is not None
    }
    known = known_comment_ids(review)
    threads_by_root = {
        thread.github_root_comment_id: thread
        for thread in review.threads
        if thread.github_root_comment_id
    }

    for comment in sorted(comments, key=lambda item: _as_int(item.get("id")) or 0):
        comment_id = _as_int(comment.get("id"))
        if comment_id is None or comment_id in known:
            continue
        if own_review_id is not None and comment.get("pull_request_review_id") == own_review_id:
            # One of this review's own inline findings. Identity is the review it was posted with,
            # not the author: the reviewer replies from the same GitHub account the token uses.
            known.add(comment_id)
            continue
        author = _author(comment)

        root = _root_of(comment, by_id)
        root_id = _as_int(root.get("id"))
        has_parent = _as_int(comment.get("in_reply_to_id")) is not None
        thread = threads_by_root.get(root_id) if root_id is not None else None

        if has_parent and thread is not None:
            _open_round(thread, comment, author)
            known.add(comment_id)
            outcome.new_rounds += 1
            continue

        if not has_parent:
            path = comment.get("path")
            if not isinstance(path, str) or not path:
                continue
            item = InboundThread(
                root_id=comment_id,
                path=path,
                line_number=_line_number(comment),
                diff_hunk=comment.get("diff_hunk")
                if isinstance(comment.get("diff_hunk"), str)
                else "",
                author=author,
                body=(comment.get("body") or "").strip(),
                created_at=_timestamp(comment),
            )
            created = new_existing_thread(review.id, item)
            db.add(created)
            threads_by_root[comment_id] = created
            known.add(comment_id)
            outcome.new_threads += 1
            continue

        outcome.warnings.append(
            f"Ignored comment {comment_id}: its top-level comment is not part of this review."
        )

    db.commit()
    db.refresh(review)
    return outcome
