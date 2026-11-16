"""Request/response models for side-by-side model comparison. Every dollar figure is an estimate."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CompareRequest(BaseModel):
    """The second model to review the same pull request with."""

    model: str = Field(min_length=1)


class ComparisonSide(BaseModel):
    id: int
    model_used: str | None = None
    thread_count: int = 0


class ComparisonMatch(BaseModel):
    """One defect both runs found, possibly anchored a line or two apart."""

    primary_thread_id: int
    comparison_thread_id: int
    file_path: str
    primary_line: int
    comparison_line: int
    snippet: str


class ComparisonItem(BaseModel):
    review_id: int
    thread_id: int
    file_path: str
    line_number: int
    origin: str
    snippet: str


class ComparisonRead(BaseModel):
    primary: ComparisonSide
    comparison: ComparisonSide
    both: list[ComparisonMatch] = Field(default_factory=list)
    primary_only: list[ComparisonItem] = Field(default_factory=list)
    comparison_only: list[ComparisonItem] = Field(default_factory=list)
    line_tolerance: int = 2


class ComparisonEstimate(BaseModel):
    """What the second run is expected to cost, from the primary's measured usage."""

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float | None = None
    note: str
