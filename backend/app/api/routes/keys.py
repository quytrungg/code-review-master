from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_db
from app.schemas.keys import (
    KeyTestResponse,
    LLMKeyCreate,
    LLMKeyRead,
    LLMKeyUpdate,
    VersionControlKeyCreate,
    VersionControlKeyRead,
    VersionControlKeyUpdate,
)
from app.services import keys_service
from app.services.keys_service import KeyError
from app.services.settings_service import get_or_create

router = APIRouter(prefix="/keys", tags=["keys"])


def _active_ids(db: Session, user_id: int) -> tuple[int | None, int | None]:
    row = get_or_create(db, user_id)
    return row.version_control_key_id, row.llm_key_id


@router.get("/version-control", response_model=list[VersionControlKeyRead])
def list_version_control(
    user: CurrentUser,
    reveal: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[VersionControlKeyRead]:
    active_id, _ = _active_ids(db, user.id)
    return [
        VersionControlKeyRead.from_row(row, active_id, reveal=reveal)
        for row in keys_service.list_version_control(db, user.id)
    ]


@router.post("/version-control", response_model=VersionControlKeyRead, status_code=201)
def create_version_control(
    payload: VersionControlKeyCreate, user: CurrentUser, db: Session = Depends(get_db)
) -> VersionControlKeyRead:
    try:
        row = keys_service.create_version_control(db, user.id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    active_id, _ = _active_ids(db, user.id)
    return VersionControlKeyRead.from_row(row, active_id)


@router.patch("/version-control/{key_id}", response_model=VersionControlKeyRead)
def update_version_control(
    key_id: int,
    payload: VersionControlKeyUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> VersionControlKeyRead:
    try:
        row = keys_service.update_version_control(
            db, keys_service.get_version_control(db, user.id, key_id), payload
        )
    except KeyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    active_id, _ = _active_ids(db, user.id)
    return VersionControlKeyRead.from_row(row, active_id)


@router.delete("/version-control/{key_id}", status_code=204, response_class=Response)
def delete_version_control(
    key_id: int, user: CurrentUser, db: Session = Depends(get_db)
) -> Response:
    try:
        keys_service.delete_version_control(
            db, user.id, keys_service.get_version_control(db, user.id, key_id)
        )
    except KeyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return Response(status_code=204)


@router.post("/version-control/{key_id}/test", response_model=KeyTestResponse)
async def test_version_control(
    key_id: int, user: CurrentUser, db: Session = Depends(get_db)
) -> KeyTestResponse:
    try:
        key = keys_service.get_version_control(db, user.id, key_id)
    except KeyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    ok, detail, metadata = await keys_service.test_version_control(key)
    return KeyTestResponse(ok=ok, detail=detail, metadata=metadata)


@router.get("/llm", response_model=list[LLMKeyRead])
def list_llm(
    user: CurrentUser,
    reveal: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[LLMKeyRead]:
    _, active_id = _active_ids(db, user.id)
    return [
        LLMKeyRead.from_row(row, active_id, reveal=reveal)
        for row in keys_service.list_llm(db, user.id)
    ]


@router.post("/llm", response_model=LLMKeyRead, status_code=201)
def create_llm(
    payload: LLMKeyCreate, user: CurrentUser, db: Session = Depends(get_db)
) -> LLMKeyRead:
    try:
        row = keys_service.create_llm(db, user.id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _, active_id = _active_ids(db, user.id)
    return LLMKeyRead.from_row(row, active_id)


@router.patch("/llm/{key_id}", response_model=LLMKeyRead)
def update_llm(
    key_id: int,
    payload: LLMKeyUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> LLMKeyRead:
    try:
        row = keys_service.update_llm(db, keys_service.get_llm(db, user.id, key_id), payload)
    except KeyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    _, active_id = _active_ids(db, user.id)
    return LLMKeyRead.from_row(row, active_id)


@router.delete("/llm/{key_id}", status_code=204, response_class=Response)
def delete_llm(key_id: int, user: CurrentUser, db: Session = Depends(get_db)) -> Response:
    try:
        keys_service.delete_llm(db, user.id, keys_service.get_llm(db, user.id, key_id))
    except KeyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return Response(status_code=204)


@router.post("/llm/{key_id}/test", response_model=KeyTestResponse)
async def test_llm(
    key_id: int, user: CurrentUser, db: Session = Depends(get_db)
) -> KeyTestResponse:
    try:
        key = keys_service.get_llm(db, user.id, key_id)
    except KeyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    ok, detail, metadata = await keys_service.test_llm(key)
    return KeyTestResponse(ok=ok, detail=detail, metadata=metadata)
