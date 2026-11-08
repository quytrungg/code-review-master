"""Per-user credential CRUD and resolution.

Every function takes the owning `user_id`: credentials never cross accounts. `settings` only
stores which key is active for that user; resolution prefers the active key when it matches the
requested provider, and otherwise falls back to the oldest key for that provider — so a review
created with `ollama-local:` still works when GitHub is the active version-control key.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import ensure_encryption_configured
from app.models.keys import (
    KEYLESS_LLM_PROVIDERS,
    LLM_PROVIDERS,
    VCS_PROVIDERS,
    LLMKey,
    VersionControlKey,
)
from app.schemas.keys import (
    LLMKeyCreate,
    LLMKeyUpdate,
    VersionControlKeyCreate,
    VersionControlKeyUpdate,
)
from app.services import github_service, gitlab_service, llm_service
from app.services.settings_service import get_or_create


class KeyError(Exception):
    """Credential operation the operator can fix (unknown provider, wrong id, …)."""

    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _normalise_base_url(value) -> str | None:
    return str(value).rstrip("/") if value else None


# --------------------------------------------------------------------------- version control


def list_version_control(db: Session, user_id: int) -> list[VersionControlKey]:
    return list(
        db.scalars(
            select(VersionControlKey)
            .where(VersionControlKey.user_id == user_id)
            .order_by(VersionControlKey.provider, VersionControlKey.id)
        )
    )


def get_version_control(db: Session, user_id: int, key_id: int) -> VersionControlKey:
    row = db.scalars(
        select(VersionControlKey).where(
            VersionControlKey.id == key_id, VersionControlKey.user_id == user_id
        )
    ).first()
    if row is None:
        raise KeyError("Version-control key not found.", 404)
    return row


def create_version_control(
    db: Session, user_id: int, payload: VersionControlKeyCreate
) -> VersionControlKey:
    if payload.provider not in VCS_PROVIDERS:
        raise KeyError(f"Unknown version-control provider '{payload.provider}'.", 422)
    ensure_encryption_configured()
    row = VersionControlKey(
        user_id=user_id,
        provider=payload.provider,
        token=payload.token,
        base_url=_normalise_base_url(payload.base_url),
        label=payload.label,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_version_control(
    db: Session, key: VersionControlKey, payload: VersionControlKeyUpdate
) -> VersionControlKey:
    if payload.token is not None:
        ensure_encryption_configured()
        key.token = payload.token
    if payload.base_url is not None:
        key.base_url = _normalise_base_url(payload.base_url)
    if payload.label is not None:
        key.label = payload.label
    db.commit()
    db.refresh(key)
    return key


def delete_version_control(db: Session, user_id: int, key: VersionControlKey) -> None:
    settings_row = get_or_create(db, user_id)
    if settings_row.version_control_key_id == key.id:
        settings_row.version_control_key_id = None
    db.delete(key)
    db.commit()


# ------------------------------------------------------------------------------------- LLM


def list_llm(db: Session, user_id: int) -> list[LLMKey]:
    return list(
        db.scalars(
            select(LLMKey).where(LLMKey.user_id == user_id).order_by(LLMKey.provider, LLMKey.id)
        )
    )


def get_llm(db: Session, user_id: int, key_id: int) -> LLMKey:
    row = db.scalars(
        select(LLMKey).where(LLMKey.id == key_id, LLMKey.user_id == user_id)
    ).first()
    if row is None:
        raise KeyError("Model-provider key not found.", 404)
    return row


def create_llm(db: Session, user_id: int, payload: LLMKeyCreate) -> LLMKey:
    if payload.provider not in LLM_PROVIDERS:
        raise KeyError(f"Unknown model provider '{payload.provider}'.", 422)
    if payload.api_key is not None:
        ensure_encryption_configured()
    row = LLMKey(
        user_id=user_id,
        provider=payload.provider,
        api_key=payload.api_key,
        base_url=_normalise_base_url(payload.base_url),
        default_model=payload.default_model,
        label=payload.label,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_llm(db: Session, key: LLMKey, payload: LLMKeyUpdate) -> LLMKey:
    if payload.api_key is not None:
        ensure_encryption_configured()
        key.api_key = payload.api_key
    if payload.base_url is not None:
        key.base_url = _normalise_base_url(payload.base_url)
    if payload.default_model is not None:
        key.default_model = payload.default_model
    if payload.label is not None:
        key.label = payload.label
    db.commit()
    db.refresh(key)
    return key


def delete_llm(db: Session, user_id: int, key: LLMKey) -> None:
    settings_row = get_or_create(db, user_id)
    if settings_row.llm_key_id == key.id:
        settings_row.llm_key_id = None
    db.delete(key)
    db.commit()


# ---------------------------------------------------------------------------------- active


def set_active(
    db: Session,
    user_id: int,
    *,
    version_control_key_id: int | None = None,
    llm_key_id: int | None = None,
    unset_version_control: bool = False,
    unset_llm: bool = False,
) -> None:
    settings_row = get_or_create(db, user_id)
    if unset_version_control:
        settings_row.version_control_key_id = None
    elif version_control_key_id is not None:
        settings_row.version_control_key_id = get_version_control(
            db, user_id, version_control_key_id
        ).id
    if unset_llm:
        settings_row.llm_key_id = None
    elif llm_key_id is not None:
        settings_row.llm_key_id = get_llm(db, user_id, llm_key_id).id
    db.commit()


def active_version_control(db: Session, user_id: int) -> VersionControlKey | None:
    settings_row = get_or_create(db, user_id)
    if settings_row.version_control_key_id is None:
        return None
    return db.get(VersionControlKey, settings_row.version_control_key_id)


def active_llm(db: Session, user_id: int) -> LLMKey | None:
    settings_row = get_or_create(db, user_id)
    if settings_row.llm_key_id is None:
        return None
    return db.get(LLMKey, settings_row.llm_key_id)


def version_control_for(db: Session, user_id: int, provider: str) -> VersionControlKey | None:
    """The key to use for a review hosted on `provider`: active first, then the oldest one."""
    active = active_version_control(db, user_id)
    if active is not None and active.provider == provider:
        return active
    return db.scalars(
        select(VersionControlKey)
        .where(
            VersionControlKey.user_id == user_id,
            VersionControlKey.provider == provider,
        )
        .order_by(VersionControlKey.id)
    ).first()


def llm_for(db: Session, user_id: int, provider: str) -> LLMKey | None:
    active = active_llm(db, user_id)
    if active is not None and active.provider == provider:
        return active
    return db.scalars(
        select(LLMKey)
        .where(LLMKey.user_id == user_id, LLMKey.provider == provider)
        .order_by(LLMKey.id)
    ).first()


def credentials_for(key: LLMKey) -> llm_service.LLMCredentials:
    return llm_service.LLMCredentials(
        provider=key.provider,
        api_key=key.api_key,
        base_url=key.effective_base_url,
        default_model=key.default_model,
    )


def credentials_for_provider(
    db: Session, user_id: int, provider: str
) -> llm_service.LLMCredentials:
    """Credentials for a model-id provider (`claude`, `openai`, `ollama-cloud`, `ollama-local`)."""
    db_provider = llm_service.DB_PROVIDER.get(provider, provider)
    key = llm_for(db, user_id, db_provider)
    if key is None:
        raise KeyError(_missing_llm_message(db_provider), 422)
    if db_provider not in KEYLESS_LLM_PROVIDERS and not key.api_key:
        raise KeyError(f"No API key stored for {db_provider}. Add one in Settings.", 422)
    return credentials_for(key)


def _missing_llm_message(provider: str) -> str:
    labels = {
        "claude": "Claude",
        "openai": "OpenAI",
        "ollama_cloud": "Ollama Cloud",
        "ollama_local": "Ollama (local)",
    }
    return f"No {labels.get(provider, provider)} key configured. Add one in Settings."


def missing_vcs_message(provider: str) -> str:
    labels = {"github": "GitHub", "gitlab": "GitLab"}
    return f"No {labels.get(provider, provider)} token configured. Add one in Settings."


# ------------------------------------------------------------------------------------ probes


async def test_version_control(key: VersionControlKey) -> tuple[bool, str, dict | None]:
    if key.provider == "github":
        return await github_service.verify_token(key.token, base_url=key.effective_base_url)
    return await gitlab_service.verify_token(key.token, base_url=key.effective_base_url)


async def test_llm(key: LLMKey) -> tuple[bool, str, dict | None]:
    base_url = key.effective_base_url
    if key.provider == "claude":
        return await llm_service.probe_claude(key.api_key or "", base_url=base_url)
    if key.provider == "openai":
        return await llm_service.probe_openai(key.api_key or "", base_url=base_url)
    if key.provider == "ollama_cloud":
        return await llm_service.probe_ollama(
            base_url, api_key=key.api_key, label="Ollama Cloud"
        )
    return await llm_service.probe_ollama(base_url, label="Ollama (local)")
