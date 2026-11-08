from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import iso_utc
from app.services.secrets import mask_secret

ConnectionTargetName = Literal["version_control", "llm"]


class SettingsUpdate(BaseModel):
    """Select the active credential.

    A field that is absent leaves the current selection; an explicit `null` clears it.
    """

    version_control_key_id: int | None = Field(default=None, ge=1)
    llm_key_id: int | None = Field(default=None, ge=1)


class ActiveKeySummary(BaseModel):
    id: int
    provider: str
    label: str | None = None
    base_url: str | None = None
    secret_masked: str | None = None
    default_model: str | None = None


class SettingsRead(BaseModel):
    version_control_key_id: int | None = None
    llm_key_id: int | None = None
    version_control: ActiveKeySummary | None = None
    llm: ActiveKeySummary | None = None
    needs_setup: bool = True
    updated_at: str | None = None

    # Populated only when the request asks for revelation.
    version_control_token: str | None = None
    llm_api_key: str | None = None

    @classmethod
    def from_rows(cls, row, version_control, llm, reveal: bool = False) -> "SettingsRead":
        return cls(
            version_control_key_id=row.version_control_key_id,
            llm_key_id=row.llm_key_id,
            version_control=(
                ActiveKeySummary(
                    id=version_control.id,
                    provider=version_control.provider,
                    label=version_control.label,
                    base_url=version_control.base_url,
                    secret_masked=mask_secret(version_control.token),
                )
                if version_control is not None
                else None
            ),
            llm=(
                ActiveKeySummary(
                    id=llm.id,
                    provider=llm.provider,
                    label=llm.label,
                    base_url=llm.base_url,
                    secret_masked=mask_secret(llm.api_key),
                    default_model=llm.default_model,
                )
                if llm is not None
                else None
            ),
            needs_setup=version_control is None or llm is None,
            updated_at=iso_utc(row.updated_at),
            version_control_token=version_control.token if (reveal and version_control) else None,
            llm_api_key=llm.api_key if (reveal and llm) else None,
        )


class ConnectionTarget(BaseModel):
    target: str
    ok: bool
    detail: str
    metadata: dict | None = None


class ConnectionTestRequest(BaseModel):
    targets: list[str] = Field(default_factory=lambda: ["version_control", "llm"])


class ConnectionTestResponse(BaseModel):
    results: list[ConnectionTarget]
