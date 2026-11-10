from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_db
from app.schemas.settings import (
    ConnectionTarget,
    ConnectionTestRequest,
    ConnectionTestResponse,
    SettingsRead,
    SettingsUpdate,
)
from app.services import keys_service
from app.services.keys_service import KeyError
from app.services.settings_service import get_or_create

router = APIRouter(prefix="/settings", tags=["settings"])


def _read(db: Session, user_id: int, reveal: bool = False) -> SettingsRead:
    row = get_or_create(db, user_id)
    return SettingsRead.from_rows(
        row,
        keys_service.active_version_control(db, user_id),
        keys_service.active_llm(db, user_id),
        reveal=reveal,
    )


@router.get("", response_model=SettingsRead)
def read_settings(
    user: CurrentUser,
    reveal: bool = Query(default=False, description="Include raw secret values for editing."),
    db: Session = Depends(get_db),
) -> SettingsRead:
    return _read(db, user.id, reveal=reveal)


@router.put("", response_model=SettingsRead)
def update_settings(
    payload: SettingsUpdate, user: CurrentUser, db: Session = Depends(get_db)
) -> SettingsRead:
    fields = payload.model_fields_set
    try:
        if "version_control_key_id" in fields:
            keys_service.set_active(
                db,
                user.id,
                version_control_key_id=payload.version_control_key_id,
                unset_version_control=payload.version_control_key_id is None,
            )
        if "llm_key_id" in fields:
            keys_service.set_active(
                db,
                user.id,
                llm_key_id=payload.llm_key_id,
                unset_llm=payload.llm_key_id is None,
            )
    except KeyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    # Soft caps: an absent field keeps the current value, an explicit null clears it.
    caps = {"monthly_token_budget", "monthly_dollar_budget"}
    if caps & fields:
        row = get_or_create(db, user.id)
        for name in caps & fields:
            setattr(row, name, getattr(payload, name))
        db.commit()
    return _read(db, user.id)


@router.post("/test-connection", response_model=ConnectionTestResponse)
async def test_connection(
    payload: ConnectionTestRequest, user: CurrentUser, db: Session = Depends(get_db)
) -> ConnectionTestResponse:
    results: list[ConnectionTarget] = []
    version_control = keys_service.active_version_control(db, user.id)
    llm = keys_service.active_llm(db, user.id)

    for target in payload.targets:
        if target == "version_control":
            if version_control is None:
                results.append(
                    ConnectionTarget(target=target, ok=False, detail="No active version-control key")
                )
                continue
            ok, detail, metadata = await keys_service.test_version_control(version_control)
            results.append(
                ConnectionTarget(target=target, ok=ok, detail=detail, metadata=metadata)
            )
        elif target == "llm":
            if llm is None:
                results.append(ConnectionTarget(target=target, ok=False, detail="No active model key"))
                continue
            ok, detail, metadata = await keys_service.test_llm(llm)
            results.append(
                ConnectionTarget(target=target, ok=ok, detail=detail, metadata=metadata)
            )
        else:
            raise HTTPException(status_code=422, detail=f"Unknown target: {target}")

    return ConnectionTestResponse(results=results)
