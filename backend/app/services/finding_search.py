"""Cross-review finding search: one normalised key per finding, plus the queries over it.

The plan chose a stored key and `LIKE` over SQLite FTS5 / PostgreSQL `tsvector`: those two engines
tokenise differently, and a portable index is worth more to one reviewer's history than stemming.
`normalise` is deliberately simple and **stable** — the migration backfill carries a copy, so
changing this function does not silently re-key the past; a future change needs its own backfill.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.base import utcnow
from app.models.review import (
    CodeReview,
    MessageRole,
    ReviewThread,
    RoundStatus,
    ThreadMessage,
    ThreadOrigin,
    ThreadRound,
)

MAX_KEY_CHARS = 255
KEY_WORDS = 12
SNIPPET_CHARS = 280

_SEVERITY = {"critical", "high", "medium", "low", "severity", "blocker", "nit"}
_WORD_RE = re.compile(r"[a-z0-9]+")
_CODE_SPAN_RE = re.compile(r"`[^`]*`")
_MARKUP_RE = re.compile(r"[*_#>\[\]()|~]")


def normalise(text: str | None) -> str:
    """Lower-cased first words of a finding, severity and Markdown stripped.

    `**High** — the query is unbounded` and `high: unbounded query` both reduce to
    `the query is unbounded …`, which is the point: the key survives a reworded title.
    """
    cleaned = _CODE_SPAN_RE.sub(" ", text or "")
    cleaned = _MARKUP_RE.sub(" ", cleaned).lower()
    words = _WORD_RE.findall(cleaned)
    while words and words[0] in _SEVERITY:
        words.pop(0)
    return " ".join(words[:KEY_WORDS])[:MAX_KEY_CHARS]


def key_for_thread(thread: ReviewThread) -> str:
    """The key for an existing thread: stored one when present, else its first assistant message."""
    if thread.norm_key:
        return thread.norm_key
    for message in thread.messages:
        if message.role == MessageRole.ASSISTANT:
            return normalise(message.content)
    return ""


@dataclass
class FindingHit:
    review_id: int
    thread_id: int
    repo_full_name: str | None
    file_path: str
    line_number: int
    origin: str
    snippet: str
    excerpt: str = ""
    accepted: bool = False
    created_at: datetime | None = None


def _first_assistant(thread: ReviewThread) -> str:
    for message in thread.messages:
        if message.role == MessageRole.ASSISTANT and (message.content or "").strip():
            return message.content.strip()
    return ""


def _is_accepted(thread: ReviewThread) -> bool:
    """Accepted means a round of this thread was published, or it was imported as published."""
    if thread.thread_status == "applied":
        return True
    return any(round_.status == RoundStatus.PUBLISHED for round_ in thread.rounds)


def _hit(thread: ReviewThread, review: CodeReview, *, excerpt: bool = False) -> FindingHit:
    text = _first_assistant(thread)
    return FindingHit(
        review_id=review.id,
        thread_id=thread.id,
        repo_full_name=review.repo_full_name,
        file_path=thread.file_path,
        line_number=thread.line_number,
        origin=thread.origin,
        snippet=text[:SNIPPET_CHARS],
        excerpt=text,
        accepted=_is_accepted(thread),
        created_at=thread.created_at,
    )


def _base_query(user_id: int):
    return (
        select(ReviewThread, CodeReview)
        .join(CodeReview, ReviewThread.review_id == CodeReview.id)
        .where(CodeReview.user_id == user_id)
        .where(ReviewThread.origin.in_((ThreadOrigin.AI_GENERATED, ThreadOrigin.CHECK)))
        .options(selectinload(ReviewThread.messages), selectinload(ReviewThread.rounds))
    )


def search(
    db: Session,
    user_id: int,
    *,
    query: str | None = None,
    repo: str | None = None,
    path: str | None = None,
    since: datetime | None = None,
    limit: int = 20,
) -> tuple[list[FindingHit], int]:
    """Findings across this account's reviews. Returns `(page, total)`.

    `q` matches the normalised key (prefix-insensitive `LIKE`) or any assistant message body; the
    two together are why a three-word phrase is usually enough even when the reworded key differs.
    """
    statement = _base_query(user_id)
    if repo:
        statement = statement.where(func.lower(CodeReview.repo_full_name) == repo.strip().lower())
    if path:
        statement = statement.where(func.lower(ReviewThread.file_path).contains(path.strip().lower()))
    if since is not None:
        statement = statement.where(ReviewThread.created_at >= since)
    if query:
        needle = query.strip().lower()
        key_like = func.lower(ReviewThread.norm_key).contains(needle)
        body_like = (
            select(ThreadMessage.id)
            .where(ThreadMessage.thread_id == ReviewThread.id)
            .where(ThreadMessage.role == MessageRole.ASSISTANT)
            .where(func.lower(ThreadMessage.content).contains(needle))
            .exists()
        )
        statement = statement.where(key_like | body_like)

    rows = list(db.execute(statement.order_by(ReviewThread.created_at.desc(), ReviewThread.id.desc())))
    hits = [_hit(thread, review) for thread, review in rows]
    total = len(hits)
    return hits[: max(1, limit)], total


def similar(
    db: Session, user_id: int, review: CodeReview, thread: ReviewThread, *, limit: int = 5
) -> list[FindingHit]:
    """Prior findings in the same repository with the same key — evidence, never "duplicate of"."""
    key = key_for_thread(thread)
    if not key or not review.repo_full_name:
        return []
    statement = (
        _base_query(user_id)
        .where(func.lower(CodeReview.repo_full_name) == review.repo_full_name.lower())
        .where(ReviewThread.id != thread.id)
        .where(ReviewThread.norm_key == key)
        .order_by(ReviewThread.created_at.desc(), ReviewThread.id.desc())
        .limit(max(1, limit))
    )
    return [_hit(found, found_review) for found, found_review in db.execute(statement)]


def recurring(
    db: Session, user_id: int, days: int, *, limit: int = 10
) -> list[dict]:
    """Keys seen in more than one review in the window, grouped in SQL.

    Grouped on the stored key, not the text: two findings that open differently but share the
    first twelve normalised words are the same pattern for this purpose. The copy says
    "recurring", never "identical".
    """
    since = utcnow() - timedelta(days=max(1, days))
    statement = (
        select(
            CodeReview.repo_full_name.label("repo_full_name"),
            ReviewThread.norm_key.label("key"),
            func.count(func.distinct(CodeReview.id)).label("reviews"),
            func.count(ReviewThread.id).label("findings"),
            func.max(ReviewThread.created_at).label("last_seen"),
        )
        .join(CodeReview, ReviewThread.review_id == CodeReview.id)
        .where(CodeReview.user_id == user_id)
        .where(CodeReview.repo_full_name.is_not(None))
        .where(ReviewThread.norm_key.is_not(None))
        .where(ReviewThread.created_at >= since)
        .group_by(CodeReview.repo_full_name, ReviewThread.norm_key)
        .having(func.count(func.distinct(CodeReview.id)) > 1)
        .order_by(
            func.count(func.distinct(CodeReview.id)).desc(),
            func.count(ReviewThread.id).desc(),
        )
        .limit(max(1, limit))
    )
    return [
        {
            "repo_full_name": row.repo_full_name,
            "key": row.key,
            "reviews": row.reviews,
            "findings": row.findings,
            "last_seen": row.last_seen,
        }
        for row in db.execute(statement)
    ]
