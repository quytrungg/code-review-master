from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_db
from app.core.config import get_settings
from app.schemas.review import ModelCatalog, ModelOption
from app.services import keys_service, llm_service, skill_loader

router = APIRouter(prefix="/models", tags=["models"])


def _add(models: dict[str, ModelOption], option: ModelOption) -> None:
    """Keep the first entry per model id: several keys may expose the same catalogue."""
    models.setdefault(option.id, option)


@router.get("", response_model=ModelCatalog)
async def list_models(user: CurrentUser, db: Session = Depends(get_db)) -> ModelCatalog:
    config = get_settings()
    keys = keys_service.list_llm(db, user.id)
    models: dict[str, ModelOption] = {}

    for key in keys:
        note = key.label or None
        # `key.provider` is the *database* form (`ollama_local`), not the model-id prefix
        # (`ollama-local`) — comparing the two silently never matches.
        if config.serverless and key.provider == llm_service.DB_PROVIDER[llm_service.OLLAMA_LOCAL]:
            # A deployed function cannot reach the operator's local daemon: hide, don't offer it.
            continue
        if key.provider == "claude" and key.api_key:
            for entry in await llm_service.list_claude_models(
                key.api_key, base_url=key.effective_base_url
            ):
                _add(
                    models,
                    ModelOption(
                        id=f"{llm_service.CLAUDE}:{entry['id']}",
                        label=entry.get("label") or entry["id"],
                        provider=llm_service.CLAUDE,
                        note=note or "Anthropic",
                    ),
                )
        elif key.provider == "openai" and key.api_key:
            for entry in await llm_service.list_openai_models(
                key.api_key, base_url=key.effective_base_url
            ):
                _add(
                    models,
                    ModelOption(
                        id=f"{llm_service.OPENAI}:{entry['id']}",
                        label=entry.get("label") or entry["id"],
                        provider=llm_service.OPENAI,
                        note=note or "OpenAI",
                    ),
                )
        elif key.provider == "ollama_cloud":
            ok, detail, metadata = await llm_service.probe_ollama(
                key.effective_base_url,
                api_key=key.api_key,
                timeout=config.ollama_timeout_s,
                label="Ollama Cloud",
            )
            names = list(metadata.get("models", [])) if ok and metadata else []
            if not names and key.default_model:
                names = [key.default_model]
            for name in names:
                _add(
                    models,
                    ModelOption(
                        id=f"{llm_service.OLLAMA_CLOUD}:{name}",
                        label=name,
                        provider=llm_service.OLLAMA_CLOUD,
                        available=ok,
                        note=note or ("Ollama Cloud" if ok else detail),
                    ),
                )
        elif key.provider == "ollama_local":
            ok, detail, metadata = await llm_service.probe_ollama(
                key.effective_base_url,
                timeout=config.ollama_timeout_s,
                label="Ollama (local)",
            )
            names = list(metadata.get("models", [])) if ok and metadata else []
            if not names and key.default_model:
                names = [key.default_model]
            for name in names:
                _add(
                    models,
                    ModelOption(
                        id=f"{llm_service.OLLAMA_LOCAL}:{name}",
                        label=name,
                        provider=llm_service.OLLAMA_LOCAL,
                        available=ok,
                        note=note or ("local" if ok else detail),
                    ),
                )

    active = keys_service.active_llm(db, user.id)
    preferred = None
    if active is not None and active.default_model:
        prefix = llm_service.MODEL_PROVIDER.get(active.provider, active.provider)
        candidate = f"{prefix}:{active.default_model}"
        if candidate in models:
            preferred = candidate

    return ModelCatalog(
        models=list(models.values()), preferred=preferred, skills=skill_loader.manifest()
    )
