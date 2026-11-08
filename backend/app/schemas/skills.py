from __future__ import annotations

from pydantic import BaseModel, Field


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


class SkillFileUploadResponse(BaseModel):
    path: str
    foundation: str
    bytes: int
