"""Standing review policies: CRUD. Evaluation rides the existing watch tick, not a route."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_db
from app.schemas.policy import CreatePolicyRequest, ReviewPolicyRead, UpdatePolicyRequest
from app.services import policy_service

router = APIRouter(prefix="/policies", tags=["policies"])


@router.get("", response_model=list[ReviewPolicyRead])
def list_policies(user: CurrentUser, db: Session = Depends(get_db)) -> list[ReviewPolicyRead]:
    return [ReviewPolicyRead.from_row(row) for row in policy_service.list_policies(db, user.id)]


@router.post("", response_model=ReviewPolicyRead, status_code=201)
def create_policy(
    payload: CreatePolicyRequest, user: CurrentUser, db: Session = Depends(get_db)
) -> ReviewPolicyRead:
    try:
        policy = policy_service.create_policy(
            db,
            user.id,
            repo_pattern=payload.repo_pattern,
            involvement=payload.involvement,
            model_id=payload.model,
            skill_foundation=payload.skill_foundation,
            max_active=payload.max_active,
            enabled=payload.enabled,
        )
    except policy_service.PolicyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return ReviewPolicyRead.from_row(policy)


@router.patch("/{policy_id}", response_model=ReviewPolicyRead)
def update_policy(
    policy_id: int,
    payload: UpdatePolicyRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> ReviewPolicyRead:
    policy = policy_service.owned_policy(db, user.id, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    try:
        policy = policy_service.update_policy(
            db,
            policy,
            repo_pattern=payload.repo_pattern,
            involvement=payload.involvement,
            model_id=payload.model,
            skill_foundation=payload.skill_foundation,
            max_active=payload.max_active,
            enabled=payload.enabled,
        )
    except policy_service.PolicyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return ReviewPolicyRead.from_row(policy)


@router.delete("/{policy_id}", status_code=204)
def delete_policy(policy_id: int, user: CurrentUser, db: Session = Depends(get_db)) -> Response:
    policy = policy_service.owned_policy(db, user.id, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    policy_service.delete_policy(db, policy)
    return Response(status_code=204)
