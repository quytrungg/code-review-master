"""Request and response models for standing review policies."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import iso_utc

Involvement = Literal["reviewer", "assignee", "author", "any"]


class CreatePolicyRequest(BaseModel):
    repo_pattern: str = Field(min_length=1, max_length=200)
    involvement: Involvement = "reviewer"
    model: str = Field(min_length=1)
    skill_foundation: str | None = None
    max_active: int = Field(default=1, ge=1, le=10)
    enabled: bool = True


class UpdatePolicyRequest(BaseModel):
    """Any subset; an absent field keeps the current value."""

    repo_pattern: str | None = Field(default=None, min_length=1, max_length=200)
    involvement: Involvement | None = None
    model: str | None = Field(default=None, min_length=1)
    skill_foundation: str | None = None
    max_active: int | None = Field(default=None, ge=1, le=10)
    enabled: bool | None = None


class ReviewPolicyRead(BaseModel):
    id: int
    repo_pattern: str
    involvement: str = "reviewer"
    model_used: str
    skill_foundation: str | None = None
    max_active: int = 1
    enabled: bool = True
    last_run_at: str | None = None
    last_error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_row(cls, row) -> "ReviewPolicyRead":
        return cls(
            id=row.id,
            repo_pattern=row.repo_pattern,
            involvement=row.involvement,
            model_used=row.model_used,
            skill_foundation=row.skill_foundation,
            max_active=row.max_active,
            enabled=bool(row.enabled),
            last_run_at=iso_utc(row.last_run_at),
            last_error=row.last_error,
            created_at=iso_utc(row.created_at),
            updated_at=iso_utc(row.updated_at),
        )
