from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import iso_utc


class ReviewWatchRead(BaseModel):
    """A watched change request. Carries the state the dashboard shows and the workspace toggles."""

    id: int
    pr_url: str
    vcs: str = "github"
    repo_full_name: str | None = None
    pr_number: int | None = None
    skill_foundation: str | None = None
    model_used: str | None = None
    last_seen_commit_id: str | None = None
    last_review_id: int | None = None
    enabled: bool = True
    last_checked_at: str | None = None
    last_error: str | None = None
    created_at: str | None = None

    @classmethod
    def from_row(cls, row) -> "ReviewWatchRead":
        return cls(
            id=row.id,
            pr_url=row.pr_url,
            vcs=row.vcs or "github",
            repo_full_name=row.repo_full_name,
            pr_number=row.pr_number,
            skill_foundation=row.skill_foundation,
            model_used=row.model_used,
            last_seen_commit_id=row.last_seen_commit_id,
            last_review_id=row.last_review_id,
            enabled=bool(row.enabled),
            last_checked_at=iso_utc(row.last_checked_at),
            last_error=row.last_error,
            created_at=iso_utc(row.created_at),
        )


class CreateWatchRequest(BaseModel):
    """Watch the pull request a review already covers; everything else is copied from it."""

    review_id: int = Field(gt=0)


class UpdateWatchRequest(BaseModel):
    enabled: bool


class WatchFailure(BaseModel):
    watch_id: int
    error: str | None = None


class TickResultRead(BaseModel):
    checked: int = 0
    unchanged: int = 0
    adopted: int = 0
    skipped: int = 0
    started: list[int] = Field(default_factory=list)
    failed: list[WatchFailure] = Field(default_factory=list)
