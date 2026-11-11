"""The PR inbox: aggregate review requests, detect whose turn it is, remember it locally.

One sync is per-account and deliberate (`POST /api/inbox/sync`): discovery runs against the GitHub
search API (`review-requested:` the user, `team-review-requested:` one of the user's teams,
`commenter:` the user), results are deduped on the PR URL, and each open PR is reconciled into a
`cached_prs` row the inbox can render without touching GitHub again.

Turn-taking is recomputed from GitHub truth on every sync, not stored as app state: the user's
latest submitted review gives the base status, and any reply newer than `last_user_action_at`
from someone else re-arms the row to `needs_review` with an unread count. An action taken on
GitHub itself (an approval posted from the web UI) moves the clock in exactly the same way.
Status detection is best-effort: one PR that cannot be read (rate limit, deleted repo) becomes a
warning line and keeps its previous cached row; the rest of the sync still completes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.cached_pr import CachedPR, InboxInvolvement, InboxStatus
from app.models.llm_call import LLMPurpose
from app.models.review import CodeReview
from app.services import github_service, keys_service, llm_service
from app.services.keys_service import KeyError

logger = logging.getLogger(__name__)

# GitHub review states the inbox maps from; DISMISSED/PENDING never land here.
_EVENT_STATUS = {
    "APPROVED": InboxStatus.APPROVED,
    "CHANGES_REQUESTED": InboxStatus.REQUEST_CHANGED,
    "COMMENTED": InboxStatus.COMMENTED,
}
_STATUS_EVENT_FOR = {
    "APPROVE": InboxStatus.APPROVED,
    "REQUEST_CHANGES": InboxStatus.REQUEST_CHANGED,
    "COMMENT": InboxStatus.COMMENTED,
}
QUICK_EVENTS = tuple(_STATUS_EVENT_FOR)
_EVENTS_REQUIRING_BODY = ("REQUEST_CHANGES", "COMMENT")


def _parse_ts(value) -> datetime | None:
    """A GitHub `2026-11-01T10:00:00Z` timestamp, tz-aware; None on anything else."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _github_key(db: Session, user_id: int):
    key = keys_service.version_control_for(db, user_id, "github")
    if key is None:
        raise KeyError(keys_service.missing_vcs_message("github"), 422)
    return key


def _queries(login: str, teams: list[dict]) -> list[str]:
    queries = [
        f"is:pr is:open review-requested:{login} archived:false",
        f"is:pr is:open commenter:{login} archived:false",
        f"is:pr is:open author:{login} archived:false",
        f"is:pr is:open assignee:{login} archived:false",
    ]
    for team in teams:
        org = (team.get("organization") or {}).get("login")
        slug = team.get("slug")
        if org and slug:
            queries.append(f"is:pr is:open team-review-requested:{org}/{slug} archived:false")
    return queries


async def _discover(token: str, base_url: str | None, login: str) -> tuple[list[dict], set[str]]:
    """Every open PR matching any query, deduped on its URL, plus the commenter-query URLs.

    The commenter set is the cheap signal for Step A: those PRs may carry own comments without a
    formal review, so their comment timelines have to be fetched either way.
    """
    merged: dict[str, dict] = {}
    commented: set[str] = set()
    for query in _queries(login, await github_service.fetch_teams(token, base_url=base_url)):
        for item in await github_service.search_open_prs(token, query, base_url=base_url):
            url = item.get("html_url") or ""
            if not url or item.get("pull_request") is None:
                continue
            merged.setdefault(url, item)
            if query.startswith("is:pr is:open commenter:"):
                commented.add(url)
    return list(merged.values()), commented


def _own_latest_review(reviews: list[dict], login: str) -> dict | None:
    latest: tuple[datetime, dict] | None = None
    for review in reviews:
        state = (review.get("state") or "").upper()
        if state not in _EVENT_STATUS:
            continue
        if (review.get("user") or {}).get("login") != login:
            continue
        submitted = _parse_ts(review.get("submitted_at"))
        if submitted is None:
            continue
        if latest is None or submitted > latest[0]:
            latest = (submitted, review)
    return latest[1] if latest else None


async def _detect_status(
    token: str, base_url: str | None, login: str, item: dict, fetch_comments: bool
) -> dict:
    """Status, last-own-action time and unread state for one PR, from GitHub."""
    owner, repo, number = github_service.parse_pr_url(item["html_url"])
    full_name = f"{owner}/{repo}"
    reviews = await github_service.fetch_pull_reviews(
        token, full_name, number, base_url=base_url
    )
    latest_review = _own_latest_review(reviews, login)

    state: str | None = None
    last_action = _parse_ts((latest_review or {}).get("submitted_at"))
    if latest_review is not None:
        state = _EVENT_STATUS[(latest_review.get("state") or "").upper()]

    comments: list[dict] = []
    # Comment timelines cost two requests per PR, so they run only for a PR the user is already
    # involved in — an own review, or a hit from the `commenter:` query.
    if fetch_comments or latest_review is not None:
        inline = await github_service.fetch_review_comments(
            token, full_name, number, base_url=base_url
        )
        conversation = await github_service.fetch_issue_comments(
            token, full_name, number, base_url=base_url
        )
        comments = [
            entry
            for entry in [*inline, *conversation]
            if _parse_ts(entry.get("created_at")) is not None
        ]
        own_comments = [
            entry for entry in comments if (entry.get("user") or {}).get("login") == login
        ]
        own_times = [ts for entry in own_comments if (ts := _parse_ts(entry.get("created_at")))]
        if own_times:
            last_action = max([*own_times, last_action] if last_action else own_times)
        if state is None and own_comments:
            state = InboxStatus.COMMENTED

    if state is None:
        state = InboxStatus.NEEDS_REVIEW

    unread = 0
    if state in InboxStatus.ACTIONABLE and last_action is not None:
        unread = sum(
            1
            for entry in comments
            if (entry.get("user") or {}).get("login") != login
            and (_parse_ts(entry.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))
            > last_action
        )
        if unread:
            # Someone answered after the user's last move: it is the user's turn again.
            state = InboxStatus.NEEDS_REVIEW

    return {
        "status": state,
        "last_user_action_at": last_action,
        "has_unread_replies": unread > 0,
        "unread_replies_count": unread,
    }


def _linked_review(db: Session, user_id: int, pr_url: str) -> CodeReview | None:
    return db.scalars(
        select(CodeReview)
        .where(CodeReview.user_id == user_id, CodeReview.pr_url == pr_url)
        .order_by(CodeReview.id.desc())
    ).first()


def _involvement(item: dict, login: str) -> str:
    """The strongest role this account holds on the PR; author beats assignee beats reviewer."""
    if (item.get("user") or {}).get("login") == login:
        return InboxInvolvement.AUTHOR
    if any((a or {}).get("login") == login for a in item.get("assignees") or []):
        return InboxInvolvement.ASSIGNEE
    return InboxInvolvement.REVIEWER


def link_review(db: Session, user_id: int, pr_url: str, review_id: int) -> None:
    """Point any cached inbox row for this PR at the review that now covers it.

    Called when a review is created, so the inbox card flips from "AI review" to
    "Open review" immediately instead of waiting for the next GitHub sync.
    """
    db.execute(
        update(CachedPR)
        .where(CachedPR.user_id == user_id, CachedPR.pr_url == pr_url)
        .values(linked_review_id=review_id)
    )
    db.commit()


async def sync_inbox(
    db: Session, user_id: int
) -> tuple[list[CachedPR], int, list[str]]:
    """Discover the user's review queue and upsert the cache. Returns (rows, gone, warnings)."""
    key = _github_key(db, user_id)
    token, base_url = key.token, key.effective_base_url

    ok, detail, metadata = await github_service.verify_token(token, base_url=base_url)
    login = (metadata or {}).get("login")
    if not ok or not login:
        raise KeyError(detail or "GitHub rejected the token. Check it in Settings.", 422)

    items, commented = await _discover(token, base_url, login)
    warnings: list[str] = []
    synced_at = utcnow()
    existing = {
        (row.repo_owner, row.repo_name, row.pr_number): row
        for row in db.scalars(select(CachedPR).where(CachedPR.user_id == user_id))
    }
    seen: set[tuple[str, str, int]] = set()

    for item in items:
        url = item["html_url"]
        try:
            owner, repo, number = github_service.parse_pr_url(url)
        except github_service.GitHubError:
            warnings.append(f"Skipped an unparseable search result ({url}).")
            continue
        coords = (owner, repo, number)
        seen.add(coords)
        row = existing.get(coords)
        try:
            detected = await _detect_status(
                token, base_url, login, item, fetch_comments=url in commented
            )
        except github_service.GitHubError as exc:
            # One unreadable PR must not fail the whole sync; keep what the cache already had.
            warnings.append(f"Could not refresh {owner}/{repo}#{number}: {exc.message}")
            if row is not None:
                row.last_synced_at = synced_at
            continue

        linked = _linked_review(db, user_id, url)
        fields = {
            "github_pr_id": int(item.get("id") or 0),
            "repo_owner": owner,
            "repo_name": repo,
            "pr_number": number,
            "pr_url": url,
            "title": item.get("title") or f"{owner}/{repo}#{number}",
            "author_username": (item.get("user") or {}).get("login", "unknown"),
            "author_avatar_url": (item.get("user") or {}).get("avatar_url"),
            "last_github_activity_at": _parse_ts(item.get("updated_at")) or synced_at,
            "linked_review_id": linked.id if linked is not None else None,
            "involvement": _involvement(item, login),
            "last_synced_at": synced_at,
            **detected,
        }
        if row is None:
            row = CachedPR(user_id=user_id, **fields)
            db.add(row)
        else:
            for name, value in fields.items():
                setattr(row, name, value)

    # PRs no longer open and matching leave the inbox.
    gone_rows = [row for coords, row in existing.items() if coords not in seen]
    gone = len(gone_rows)
    if gone_rows:
        db.execute(delete(CachedPR).where(CachedPR.id.in_([row.id for row in gone_rows])))

    db.commit()
    return list_inbox(db, user_id), gone, warnings


def list_inbox(
    db: Session,
    user_id: int,
    *,
    status: str | None = None,
    repo: str | None = None,
    unread: bool = False,
) -> list[CachedPR]:
    query = select(CachedPR).where(CachedPR.user_id == user_id)
    if status:
        if status not in InboxStatus.ALL:
            raise KeyError(
                f"Unknown status '{status}'. Expected one of: {', '.join(InboxStatus.ALL)}.", 422
            )
        query = query.where(CachedPR.status == status)
    if repo:
        if "/" not in repo:
            raise KeyError("Filter `repo` expects `owner/name`.", 422)
        owner, _, name = repo.partition("/")
        query = query.where(CachedPR.repo_owner == owner, CachedPR.repo_name == name)
    if unread:
        query = query.where(CachedPR.has_unread_replies.is_(True))
    return list(
        db.scalars(query.order_by(CachedPR.last_github_activity_at.desc(), CachedPR.id.desc()))
    )


async def quick_review(
    db: Session, user_id: int, cached_pr_id: int, event: str, body: str | None
) -> CachedPR:
    """Post one top-level review (approve / request changes / comment) to the cached PR."""
    row = db.scalars(
        select(CachedPR).where(CachedPR.id == cached_pr_id, CachedPR.user_id == user_id)
    ).first()
    if row is None:
        # Ownership rule: another account's row is a 404, never a 403.
        raise KeyError("Pull request not found.", 404)
    if event not in QUICK_EVENTS:
        raise KeyError(f"Unknown event '{event}'. Expected one of: {', '.join(QUICK_EVENTS)}.", 422)
    text = (body or "").strip()
    if event in _EVENTS_REQUIRING_BODY and not text:
        raise KeyError(f"A {event.lower().replace('_', ' ')} review needs a comment body.", 422)

    key = _github_key(db, user_id)
    payload: dict = {"event": event}
    if text:
        payload["body"] = text
    await github_service.post_review(
        key.token,
        f"{row.repo_owner}/{row.repo_name}",
        row.pr_number,
        payload,
        base_url=key.effective_base_url,
    )

    # Mirror what the next sync would learn from GitHub: own action, turn passed, inbox clean.
    row.status = _STATUS_EVENT_FOR[event]
    row.last_user_action_at = utcnow()
    row.has_unread_replies = False
    row.unread_replies_count = 0
    db.commit()
    db.refresh(row)
    logger.info("Quick review %s on %s/%s#%d", event, row.repo_owner, row.repo_name, row.pr_number)
    return row


async def polish(db: Session, user_id: int, text: str) -> str:
    """Rewrite a quick-review draft for clarity with the account's active model key."""
    draft = (text or "").strip()
    if not draft:
        raise KeyError("Nothing to polish — write the comment first.", 422)
    key = keys_service.active_llm(db, user_id)
    if key is None:
        raise KeyError("No model key configured. Add one in Settings.", 422)
    prefix = llm_service.MODEL_PROVIDER.get(key.provider)
    if prefix is None or not key.default_model:
        raise KeyError(
            "The active model key has no default model. Pick one in Settings.", 422
        )
    result = await llm_service.generate(
        keys_service.credentials_for(key),
        llm_service.parse_model_id(f"{prefix}:{key.default_model}"),
        (
            "You rewrite a code review comment. Return only the rewritten comment: same meaning, "
            "specific, courteous, no greeting, no sign-off, no surrounding quotes."
        ),
        draft,
        purpose=LLMPurpose.POLISH,
    )
    polished = result.text.strip()
    if not polished:
        raise llm_service.LLMError("The model returned an empty rewrite; the draft was kept.")
    return polished
