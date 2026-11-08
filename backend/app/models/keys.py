"""Version-control and model-provider credentials.

One row per configured credential. `settings` points at the active one of each family, so an
operator can keep a GitHub and a GitLab token (or a Claude and an Ollama key) side by side and
switch between them without losing either.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow
from app.db.types import EncryptedText

VCS_GITHUB = "github"
VCS_GITLAB = "gitlab"
VCS_PROVIDERS = (VCS_GITHUB, VCS_GITLAB)

LLM_CLAUDE = "claude"
LLM_OPENAI = "openai"
LLM_OLLAMA_CLOUD = "ollama_cloud"
LLM_OLLAMA_LOCAL = "ollama_local"
LLM_PROVIDERS = (LLM_CLAUDE, LLM_OPENAI, LLM_OLLAMA_CLOUD, LLM_OLLAMA_LOCAL)

# Providers that need no secret (a local daemon is protected by the network, not a key).
KEYLESS_LLM_PROVIDERS = (LLM_OLLAMA_LOCAL,)

VCS_DEFAULT_BASE_URLS = {
    VCS_GITHUB: "https://api.github.com",
    VCS_GITLAB: "https://gitlab.com",
}

LLM_DEFAULT_BASE_URLS = {
    LLM_CLAUDE: "https://api.anthropic.com",
    LLM_OPENAI: "https://api.openai.com/v1",
    LLM_OLLAMA_CLOUD: "https://ollama.com",
    LLM_OLLAMA_LOCAL: "http://localhost:11434",
}


class VersionControlKey(Base):
    """A token for one version-control host (GitHub, a GitLab instance, …)."""

    __tablename__ = "version_control_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    # Encrypted at rest; decrypted only in memory for an outbound call or a reveal read.
    token: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    # NULL means the provider default; set it for self-hosted GitLab.
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    @property
    def effective_base_url(self) -> str:
        return (self.base_url or VCS_DEFAULT_BASE_URLS[self.provider]).rstrip("/")


class LLMKey(Base):
    """A model provider credential (or, for a local daemon, just its base URL)."""

    __tablename__ = "llm_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    api_key: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Model suggested by default for this provider (used to prime the review picker).
    default_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    @property
    def effective_base_url(self) -> str:
        return (self.base_url or LLM_DEFAULT_BASE_URLS[self.provider]).rstrip("/")
