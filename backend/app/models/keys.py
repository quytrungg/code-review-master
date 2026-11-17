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
# Hosted OpenCode Console inference (OpenAI-compatible, bearer key).
LLM_OPENCODE = "opencode"
LLM_PROVIDERS = (LLM_CLAUDE, LLM_OPENAI, LLM_OLLAMA_CLOUD, LLM_OLLAMA_LOCAL, LLM_OPENCODE)

# How an `llm_keys` row authenticates (`auth_type`). Claude is the only provider with both today:
# an API key uses `x-api-key`, a Claude sign-in uses an OAuth bearer token plus a refresh token.
AUTH_API_KEY = "api_key"
AUTH_OAUTH = "oauth"
AUTH_TYPES = (AUTH_API_KEY, AUTH_OAUTH)

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
    # OpenCode Go keys use `.../inference/go/openai/v1`; the base URL is editable per key.
    LLM_OPENCODE: "https://opencode.ai/inference/openai/v1",
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
    # `api_key` or `oauth`. An OAuth row stores the access token in `api_key` and keeps the
    # refresh token and expiry beside it; everything else stays an API key.
    auth_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AUTH_API_KEY, server_default=AUTH_API_KEY
    )
    refresh_token: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    # When the OAuth access token stops working. Refreshed 120 s early by `keys_service`.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
