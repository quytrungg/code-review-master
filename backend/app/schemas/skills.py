from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# The local CLI-agent stores the evolve analysis can mine for correction evidence.
EvolutionSessionSource = Literal["claude", "codex", "hermes"]


class SessionSourceRead(BaseModel):
    """One agent-session folder the browser may ask the analysis to mine."""

    id: EvolutionSessionSource
    label: str
    path: str
    available: bool = True
    detail: str | None = None


class FoundationRead(BaseModel):
    id: str
    label: str
    is_default: bool = False
    file_count: int = 0
    total_chars: int = 0
    files: list[str] = Field(default_factory=list)


class SkillsResponse(BaseModel):
    default: str
    # False on a read-only deployment (Vercel): the bundled library is the only source.
    uploads_enabled: bool = True
    foundations: list[FoundationRead] = Field(default_factory=list)
    # Local CLI-agent session folders the evolve analysis can read on this machine.
    session_sources: list[SessionSourceRead] = Field(default_factory=list)


class SkillFileUploadResponse(BaseModel):
    path: str
    foundation: str
    bytes: int


# -------------------------------------------------------------------------- skill evolution


class EvolutionAnalyzeRequest(BaseModel):
    """Ask the model to propose guideline edits based on the recent review history."""

    # How far back to look. The window is in days.
    days: int = Field(default=30, ge=1, le=365)
    # The model that runs the meta-analysis, e.g. "claude:claude-sonnet-4-5-20250929".
    model: str = Field(min_length=1)
    # Optionally add the last `days` of one local CLI-agent session store as evidence.
    session_source: EvolutionSessionSource | None = None


class EvolutionFileModification(BaseModel):
    file_path: str
    action: Literal["modify", "create", "delete"] = "modify"
    rationale: str = ""
    evidence_review_ids: list[int] = Field(default_factory=list)
    original_content: str = ""
    proposed_content: str = ""
    unified_diff: str = ""


class EvolutionHistory(BaseModel):
    days: int = 30
    reviews: int = 0
    threads: int = 0
    interactions: int = 0
    # Present when the operator also asked for a local agent session store.
    session_source: EvolutionSessionSource | None = None
    sessions: int = 0
    exchanges: int = 0


class EvolutionAnalysisResponse(BaseModel):
    analysis_summary: str = ""
    file_modifications: list[EvolutionFileModification] = Field(default_factory=list)
    history: EvolutionHistory = Field(default_factory=EvolutionHistory)
    warnings: list[str] = Field(default_factory=list)


class EvolutionFileChange(BaseModel):
    """One approved edit. `content` is the operator's final text, after any in-browser edit."""

    file_path: str = Field(min_length=1)
    action: Literal["modify", "create", "delete"] = "modify"
    content: str = ""


class EvolutionApplyRequest(BaseModel):
    files: list[EvolutionFileChange] = Field(min_length=1, max_length=50)


class EvolutionApplyResponse(BaseModel):
    foundation: str
    applied: list[str] = Field(default_factory=list)
    # Where the previous state was copied, so the change can be undone by hand.
    backup_path: str | None = None
    warnings: list[str] = Field(default_factory=list)


class EvolutionCloneRequest(EvolutionApplyRequest):
    new_foundation_name: str = Field(min_length=1, max_length=50)


class EvolutionCloneResponse(BaseModel):
    foundation: FoundationRead
    applied: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
