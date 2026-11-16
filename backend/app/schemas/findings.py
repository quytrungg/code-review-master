"""Response models for cross-review finding search and the recurring-issue panel."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import iso_utc


class FindingHitRead(BaseModel):
    """One prior finding. `snippet` is truncated; `excerpt` is deliberately absent from the API."""

    review_id: int
    thread_id: int
    repo_full_name: str | None = None
    file_path: str
    line_number: int
    origin: str
    snippet: str
    accepted: bool = False
    created_at: str | None = None

    @classmethod
    def from_hit(cls, hit) -> "FindingHitRead":
        return cls(
            review_id=hit.review_id,
            thread_id=hit.thread_id,
            repo_full_name=hit.repo_full_name,
            file_path=hit.file_path,
            line_number=hit.line_number,
            origin=hit.origin,
            snippet=hit.snippet,
            accepted=hit.accepted,
            created_at=iso_utc(hit.created_at),
        )


class FindingSearchResponse(BaseModel):
    items: list[FindingHitRead] = Field(default_factory=list)
    total: int = 0


class SimilarFindingsResponse(BaseModel):
    items: list[FindingHitRead] = Field(default_factory=list)


class RecurringFindingRead(BaseModel):
    """A key seen in more than one review in the same repository. Evidence, not a duplicate claim."""

    repo_full_name: str
    key: str
    reviews: int
    findings: int
    last_seen: str | None = None
