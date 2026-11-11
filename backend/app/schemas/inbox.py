from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import iso_utc


class CachedPRRead(BaseModel):
    """One pull request in the inbox cache — everything a card renders without GitHub."""

    id: int
    pr_url: str
    repo_owner: str
    repo_name: str
    pr_number: int
    title: str
    author_username: str
    author_avatar_url: str | None = None
    status: str = "needs_review"
    has_unread_replies: bool = False
    unread_replies_count: int = 0
    last_user_action_at: str | None = None
    involvement: str = "reviewer"
    last_github_activity_at: str | None = None
    linked_review_id: int | None = None
    last_synced_at: str | None = None

    @classmethod
    def from_row(cls, row) -> "CachedPRRead":
        return cls(
            id=row.id,
            pr_url=row.pr_url,
            repo_owner=row.repo_owner,
            repo_name=row.repo_name,
            pr_number=row.pr_number,
            title=row.title,
            author_username=row.author_username,
            author_avatar_url=row.author_avatar_url,
            status=row.status,
            has_unread_replies=bool(row.has_unread_replies),
            unread_replies_count=row.unread_replies_count,
            last_user_action_at=iso_utc(row.last_user_action_at),
            involvement=row.involvement or "reviewer",
            last_github_activity_at=iso_utc(row.last_github_activity_at),
            linked_review_id=row.linked_review_id,
            last_synced_at=iso_utc(row.last_synced_at),
        )


class InboxSyncResponse(BaseModel):
    items: list[CachedPRRead]
    # Rows dropped because the PR is closed or no longer requests this account.
    disappeared: int = 0
    # One sentence per PR whose refresh failed; sync is best-effort per PR.
    warnings: list[str] = Field(default_factory=list)


class QuickReviewRequest(BaseModel):
    cached_pr_id: int = Field(gt=0)
    event: str
    body: str | None = None


class PolishRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class PolishResponse(BaseModel):
    text: str
