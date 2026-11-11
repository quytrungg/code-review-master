from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import iso_utc
from app.schemas.watch import ReviewWatchRead


class CreateReviewRequest(BaseModel):
    pr_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    # Core Skill Foundation directory id; defaults to the built-in `code-review`.
    skill_foundation: str | None = None


class CreateReviewAccepted(BaseModel):
    id: int
    status: str
    skill_foundation: str | None = None


class RawFinding(BaseModel):
    """One model-reported finding, before it is anchored to a real diff line."""

    model_config = ConfigDict(populate_by_name=True)

    file_path: str = Field(alias="filePath")
    line_number: int = Field(alias="lineNumber")
    diff_hunk: str = Field(default="", alias="diffHunk")
    initial_comment: str = Field(alias="initialComment")

    @field_validator("line_number", mode="before")
    @classmethod
    def _coerce_line(cls, value):
        if isinstance(value, str) and value.strip().lstrip("+").isdigit():
            return int(value.strip().lstrip("+"))
        return value

    @field_validator("initial_comment")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("initialComment is empty")
        return value


class ThreadMessageRead(BaseModel):
    id: int
    role: str
    content: str
    round_number: int = 1
    is_external: bool = False
    author: str | None = None
    created_at: str | None = None

    @classmethod
    def from_row(cls, row) -> "ThreadMessageRead":
        return cls(
            id=row.id,
            role=row.role,
            content=row.content,
            round_number=getattr(row, "round_number", 1) or 1,
            is_external=bool(getattr(row, "is_external", False)),
            author=getattr(row, "author", None),
            created_at=iso_utc(row.created_at),
        )


class ThreadRoundRead(BaseModel):
    id: int
    round_number: int = 1
    inbound_github_comment_id: int | None = None
    inbound_author: str | None = None
    inbound_body: str | None = None
    final_summary: str | None = None
    status: str = "drafting"
    published_github_comment_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_row(cls, row) -> "ThreadRoundRead":
        return cls(
            id=row.id,
            round_number=getattr(row, "round_number", 1) or 1,
            inbound_github_comment_id=getattr(row, "inbound_github_comment_id", None),
            inbound_author=getattr(row, "inbound_author", None),
            inbound_body=getattr(row, "inbound_body", None),
            final_summary=getattr(row, "final_summary", None),
            status=getattr(row, "status", "drafting"),
            published_github_comment_id=getattr(row, "published_github_comment_id", None),
            created_at=iso_utc(getattr(row, "created_at", None)),
            updated_at=iso_utc(getattr(row, "updated_at", None)),
        )


class ReviewThreadRead(BaseModel):
    id: int
    review_id: int
    ordinal: int = 0
    origin: str = "AI_GENERATED"
    github_root_comment_id: int | None = None
    original_author: str | None = None
    current_round: int = 1
    thread_status: str = "active"
    file_path: str
    line_number: int
    diff_hunk: str
    side: str = "RIGHT"
    summary: str | None = None
    dropped: bool = False
    created_at: str | None = None
    messages: list[ThreadMessageRead] = Field(default_factory=list)
    rounds: list[ThreadRoundRead] = Field(default_factory=list)

    @classmethod
    def from_row(cls, row, ordinal: int = 0) -> "ReviewThreadRead":
        return cls(
            id=row.id,
            review_id=row.review_id,
            ordinal=ordinal,
            origin=getattr(row, "origin", "AI_GENERATED") or "AI_GENERATED",
            github_root_comment_id=getattr(row, "github_root_comment_id", None),
            original_author=getattr(row, "original_author", None),
            current_round=getattr(row, "current_round", 1) or 1,
            thread_status=getattr(row, "thread_status", "active") or "active",
            file_path=row.file_path,
            line_number=row.line_number,
            diff_hunk=row.diff_hunk or "",
            side=row.side or "RIGHT",
            summary=row.summary,
            dropped=bool(row.dropped),
            created_at=iso_utc(row.created_at),
            messages=[ThreadMessageRead.from_row(message) for message in row.messages],
            rounds=[ThreadRoundRead.from_row(item) for item in getattr(row, "rounds", [])],
        )


class ReviewUsage(BaseModel):
    """What one review's model calls cost, in counts only — see `models/llm_call.py`."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None
    latency_ms: int = 0


class CodeReviewSummary(BaseModel):
    id: int
    pr_url: str
    vcs: str = "github"
    pr_title: str | None = None
    pr_number: int | None = None
    repo_full_name: str | None = None
    model_used: str | None = None
    skill_foundation: str | None = None
    status: str
    verdict: str | None = None
    thread_count: int = 0
    # Set on a delta review: the review it continues, and what started it (`watch`).
    parent_review_id: int | None = None
    trigger: str | None = None
    # Filled on detail responses (`routes/reviews.py::_detail`); the list stays a single query.
    usage: ReviewUsage | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_row(cls, row) -> "CodeReviewSummary":
        return cls(
            id=row.id,
            pr_url=row.pr_url,
            vcs=getattr(row, "vcs", "github") or "github",
            pr_title=row.pr_title,
            pr_number=row.pr_number,
            repo_full_name=row.repo_full_name,
            model_used=row.model_used,
            skill_foundation=row.skill_foundation,
            status=row.status,
            verdict=row.verdict,
            thread_count=len(row.threads),
            parent_review_id=getattr(row, "parent_review_id", None),
            trigger=getattr(row, "trigger", None),
            created_at=iso_utc(row.created_at),
            updated_at=iso_utc(row.updated_at),
        )


class CodeReviewDetail(CodeReviewSummary):
    commit_id: str | None = None
    error: str | None = None
    notes: str | None = None
    suggested_verdict: str | None = None
    confidence_percentage: int | None = None
    suggested_verdict_note: str | None = None
    github_review_url: str | None = None
    # The watch covering this pull request, when there is one: drives the workspace toggle.
    watch: ReviewWatchRead | None = None
    threads: list[ReviewThreadRead] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_row(cls, row, warnings: list[str] | None = None) -> "CodeReviewDetail":
        stored = [line for line in (row.notes or "").split("\n") if line.strip()]
        return cls(
            **CodeReviewSummary.from_row(row).model_dump(),
            commit_id=row.commit_id,
            error=row.error,
            notes=row.notes,
            suggested_verdict=row.suggested_verdict,
            confidence_percentage=row.confidence_percentage,
            suggested_verdict_note=getattr(row, "suggested_verdict_note", None),
            github_review_url=row.github_review_url,
            threads=[
                ReviewThreadRead.from_row(thread, ordinal=index + 1)
                for index, thread in enumerate(row.threads)
            ],
            warnings=stored if warnings is None else warnings,
        )


class ModelOption(BaseModel):
    id: str
    label: str
    provider: str
    available: bool = True
    note: str | None = None


class ModelCatalog(BaseModel):
    models: list[ModelOption] = Field(default_factory=list)
    # Model id suggested by the active key's `default_model`, if it is in the list.
    preferred: str | None = None
    skills: list[str] = Field(default_factory=list)


class DiscussThread(BaseModel):
    thread_id: int
    message: str = Field(min_length=1, max_length=4000)


class DiscussRequest(BaseModel):
    threads: list[DiscussThread] = Field(min_length=1, max_length=20)


class DiscussResult(BaseModel):
    thread_id: int
    ok: bool
    error: str | None = None
    references: list[int] = Field(default_factory=list)


class DiscussResponse(BaseModel):
    review: CodeReviewDetail
    results: list[DiscussResult] = Field(default_factory=list)
    # True when the review-level verdict was recomputed from the discussion.
    opinion_refreshed: bool = False
    warnings: list[str] = Field(default_factory=list)


class ApplyRequest(BaseModel):
    event: Literal["APPROVE", "REQUEST_CHANGES", "COMMENT"] = "COMMENT"
    thread_ids: list[int] | None = None


class ApplyResponse(BaseModel):
    review: CodeReviewDetail
    github_review_url: str | None = None
    comments_posted: int = 0
    replies_posted: int = 0
    summarised: bool = False
    dropped: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SyncResponse(BaseModel):
    review: CodeReviewDetail
    new_threads: int = 0
    new_rounds: int = 0
    warnings: list[str] = Field(default_factory=list)


class RoundDecisionRequest(BaseModel):
    """`accept` publishes the round on the next apply; `push_back` never publishes it.

    `publish` and `resolve` are kept as aliases so an older client keeps working.
    """

    decision: Literal["accept", "push_back", "publish", "resolve"]
    summary: str | None = Field(default=None, max_length=8000)


class RoundDecisionResponse(BaseModel):
    review: CodeReviewDetail
    warnings: list[str] = Field(default_factory=list)


class LessonDraftResponse(BaseModel):
    """A model-drafted rule the reviewer can edit before applying — never applied as-is."""

    title: str
    body: str


class LessonApplyRequest(BaseModel):
    foundation_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=8000)


class LessonApplyResponse(BaseModel):
    path: str
    foundation: str
    lesson_id: int
