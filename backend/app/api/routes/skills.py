from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_db
from app.core.config import get_settings
from app.schemas.skills import (
    EvolutionAnalyzeRequest,
    EvolutionAnalysisResponse,
    EvolutionApplyRequest,
    EvolutionApplyResponse,
    EvolutionCloneRequest,
    EvolutionCloneResponse,
    EvolutionFileModification,
    EvolutionHistory,
    FoundationRead,
    SkillFileUploadResponse,
    SkillsResponse,
)
from app.services import skill_analyzer_service, skills_service
from app.services.skill_analyzer_service import EvolutionError
from app.services.skills_service import SkillError

router = APIRouter(prefix="/skills", tags=["skills"])


def _raise(exc: SkillError) -> NoReturn:
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


# -------------------------------------------------------------------------- skill evolution


@router.post("/{foundation_id}/analyze-history", response_model=EvolutionAnalysisResponse)
async def analyze_history(
    foundation_id: str,
    payload: EvolutionAnalyzeRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> EvolutionAnalysisResponse:
    """Propose guideline edits from this account's recent review history."""
    try:
        result = await skill_analyzer_service.analyse(
            db, user.id, foundation_id, payload.days, payload.model
        )
    except EvolutionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except SkillError as exc:
        _raise(exc)

    return EvolutionAnalysisResponse(
        analysis_summary=result.summary,
        file_modifications=[
            EvolutionFileModification(
                file_path=proposal.file_path,
                action=proposal.action,
                rationale=proposal.rationale,
                evidence_review_ids=proposal.evidence_review_ids,
                original_content=proposal.original_content,
                proposed_content=proposal.proposed_content,
                unified_diff=proposal.unified_diff,
            )
            for proposal in result.proposals
        ],
        history=EvolutionHistory(
            days=result.digest.days,
            reviews=result.digest.review_count,
            threads=result.digest.thread_count,
            interactions=result.digest.interaction_count,
        ),
        warnings=result.warnings,
    )


@router.post("/{foundation_id}/apply", response_model=EvolutionApplyResponse)
def apply_evolution(
    foundation_id: str,
    payload: EvolutionApplyRequest,
) -> EvolutionApplyResponse:
    """Write the approved edits into a foundation in place, after backing it up."""
    try:
        applied, backup = skills_service.apply_file_changes(
            foundation_id,
            [
                skills_service.FileChange(
                    file_path=item.file_path, action=item.action, content=item.content
                )
                for item in payload.files
            ],
        )
    except SkillError as exc:
        _raise(exc)
    return EvolutionApplyResponse(
        foundation=foundation_id,
        applied=applied,
        backup_path=str(backup),
    )


@router.post("/{foundation_id}/clone-and-apply", response_model=EvolutionCloneResponse)
def clone_and_apply_evolution(
    foundation_id: str,
    payload: EvolutionCloneRequest,
) -> EvolutionCloneResponse:
    """Copy a foundation into a new one and write the approved edits into the copy."""
    try:
        info, applied = skills_service.clone_foundation(
            foundation_id,
            payload.new_foundation_name,
            [
                skills_service.FileChange(
                    file_path=item.file_path, action=item.action, content=item.content
                )
                for item in payload.files
            ],
        )
    except SkillError as exc:
        _raise(exc)
    return EvolutionCloneResponse(
        foundation=FoundationRead(
            id=info.id,
            label=info.label,
            is_default=info.is_default,
            file_count=info.file_count,
            total_chars=info.total_chars,
            files=info.files,
        ),
        applied=applied,
    )
