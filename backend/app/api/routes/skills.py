from __future__ import annotations

from fastapi import APIRouter, File, Form, Response, UploadFile

from app.core.config import get_settings
from app.schemas.skills import FoundationRead, SkillFileUploadResponse, SkillsResponse
from app.services import skills_service
from app.services.skills_service import SkillError

router = APIRouter(prefix="/skills", tags=["skills"])


def _raise(exc: SkillError) -> None:
    from fastapi import HTTPException

    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("", response_model=SkillsResponse)
def list_skills() -> SkillsResponse:
    foundations = skills_service.list_foundations()
    return SkillsResponse(
        default=skills_service.DEFAULT_FOUNDATION,
        uploads_enabled=not get_settings().serverless,
        foundations=[
            FoundationRead(
                id=info.id,
                label=info.label,
                is_default=info.is_default,
                file_count=info.file_count,
                total_chars=info.total_chars,
                files=info.files,
            )
            for info in foundations
        ],
    )


@router.post("/files", response_model=SkillFileUploadResponse, status_code=201)
async def upload_skill_file(file: UploadFile = File(...)) -> SkillFileUploadResponse:
    try:
        skills_service.require_writable()
    except SkillError as exc:
        _raise(exc)
    payload = await file.read()
    try:
        relative, foundation = skills_service.save_skill_file(file.filename or "", payload)
    except SkillError as exc:
        _raise(exc)
    return SkillFileUploadResponse(path=relative, foundation=foundation, bytes=len(payload))


@router.post("/foundations", response_model=FoundationRead, status_code=201)
async def create_foundation(
    name: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    archive: UploadFile | None = File(default=None),
) -> FoundationRead:
    try:
        skills_service.require_writable()
    except SkillError as exc:
        _raise(exc)
    try:
        if archive is not None and archive.filename:
            info = skills_service.create_foundation_from_zip(name, await archive.read())
        else:
            uploads = [(item.filename or "", await item.read()) for item in files if item.filename]
            info = skills_service.create_foundation_from_files(name, uploads)
    except SkillError as exc:
        _raise(exc)
    return FoundationRead(
        id=info.id,
        label=info.label,
        is_default=info.is_default,
        file_count=info.file_count,
        total_chars=info.total_chars,
        files=info.files,
    )


@router.delete("/foundations/{foundation_id}", status_code=204, response_class=Response)
def delete_foundation(foundation_id: str) -> Response:
    try:
        skills_service.require_writable()
        skills_service.delete_foundation(foundation_id)
    except SkillError as exc:
        _raise(exc)
    return Response(status_code=204)
