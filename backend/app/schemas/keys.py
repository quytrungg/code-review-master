from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

from app.models.keys import KEYLESS_LLM_PROVIDERS
from app.schemas.common import iso_utc
from app.services.secrets import mask_secret

VcsProvider = Literal["github", "gitlab"]
LLMProvider = Literal["claude", "openai", "ollama_cloud", "ollama_local", "opencode"]

_SECRET_MAX = 500


def _strip(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) else value


class VersionControlKeyCreate(BaseModel):
    provider: VcsProvider
    token: str = Field(min_length=1, max_length=_SECRET_MAX)
    base_url: HttpUrl | None = None
    label: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _clean(self) -> "VersionControlKeyCreate":
        self.token = _strip(self.token) or ""
        if not self.token:
            raise ValueError("token cannot be empty")
        if self.label is not None:
            self.label = self.label.strip() or None
        return self


class VersionControlKeyUpdate(BaseModel):
    """Replace the token and/or adjust the description. Omitted fields stay as they are."""

    token: str | None = Field(default=None, min_length=1, max_length=_SECRET_MAX)
    base_url: HttpUrl | None = None
    label: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _clean(self) -> "VersionControlKeyUpdate":
        if isinstance(self.token, str):
            self.token = self.token.strip()
            if not self.token:
                raise ValueError("token cannot be empty; delete the key instead")
        if isinstance(self.label, str):
            self.label = self.label.strip() or None
        return self


class LLMKeyCreate(BaseModel):
    provider: LLMProvider
    api_key: str | None = Field(default=None, max_length=_SECRET_MAX)
    base_url: HttpUrl | None = None
    default_model: str | None = Field(default=None, max_length=200)
    label: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _clean(self) -> "LLMKeyCreate":
        if isinstance(self.api_key, str):
            self.api_key = self.api_key.strip() or None
        if self.provider not in KEYLESS_LLM_PROVIDERS and not self.api_key:
            raise ValueError(f"api_key is required for provider '{self.provider}'")
        if isinstance(self.default_model, str):
            self.default_model = self.default_model.strip() or None
        if isinstance(self.label, str):
            self.label = self.label.strip() or None
        return self


class LLMKeyUpdate(BaseModel):
    api_key: str | None = Field(default=None, max_length=_SECRET_MAX)
    base_url: HttpUrl | None = None
    default_model: str | None = Field(default=None, max_length=200)
    label: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _clean(self) -> "LLMKeyUpdate":
        if isinstance(self.api_key, str):
            self.api_key = self.api_key.strip()
            if not self.api_key:
                raise ValueError("api_key cannot be empty; delete the key instead")
        if isinstance(self.default_model, str):
            self.default_model = self.default_model.strip() or None
        if isinstance(self.label, str):
            self.label = self.label.strip() or None
        return self


class ClaudeOAuthStart(BaseModel):
    """Everything the browser needs to open the Claude sign-in page."""

    authorize_url: str
    expires_at: str | None = None


class ClaudeOAuthComplete(BaseModel):
    """The code claude.ai shows; it may carry the state as `code#state`."""

    code: str = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def _clean(self) -> "ClaudeOAuthComplete":
        self.code = self.code.strip()
        if not self.code:
            raise ValueError("code cannot be empty")
        return self


class VersionControlKeyRead(BaseModel):
    id: int
    provider: str
    base_url: str | None
    label: str | None
    token_masked: str | None
    is_active: bool = False
    created_at: str | None = None
    updated_at: str | None = None
    token: str | None = None  # only with ?reveal=true

    @classmethod
    def from_row(cls, row, active_id: int | None, reveal: bool = False) -> "VersionControlKeyRead":
        return cls(
            id=row.id,
            provider=row.provider,
            base_url=row.base_url,
            label=row.label,
            token_masked=mask_secret(row.token),
            is_active=row.id == active_id,
            created_at=iso_utc(row.created_at),
            updated_at=iso_utc(row.updated_at),
            token=row.token if reveal else None,
        )


class LLMKeyRead(BaseModel):
    id: int
    provider: str
    base_url: str | None
    default_model: str | None
    label: str | None
    api_key_masked: str | None
    is_active: bool = False
    # How this credential authenticates. A Claude sign-in reports `oauth`, keeps its refresh token
    # server-side only, and shows when the access token stops working.
    auth_type: str = "api_key"
    has_refresh_token: bool = False
    expires_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    api_key: str | None = None  # only with ?reveal=true

    @classmethod
    def from_row(cls, row, active_id: int | None, reveal: bool = False) -> "LLMKeyRead":
        return cls(
            id=row.id,
            provider=row.provider,
            base_url=row.base_url,
            default_model=row.default_model,
            label=row.label,
            api_key_masked=mask_secret(row.api_key),
            is_active=row.id == active_id,
            auth_type=getattr(row, "auth_type", "api_key") or "api_key",
            has_refresh_token=bool(getattr(row, "refresh_token", None)),
            expires_at=iso_utc(getattr(row, "expires_at", None)),
            created_at=iso_utc(row.created_at),
            updated_at=iso_utc(row.updated_at),
            api_key=row.api_key if reveal else None,
        )


class KeyTestResponse(BaseModel):
    ok: bool
    detail: str
    metadata: dict | None = None
