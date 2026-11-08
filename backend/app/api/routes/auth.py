from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_db
from app.core.config import get_settings
from app.schemas.auth import CredentialsRequest, UserRead
from app.services import auth_service
from app.services.auth_service import AuthError

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        auth_service.SESSION_COOKIE,
        token,
        max_age=auth_service.SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


@router.post("/signup", response_model=UserRead, status_code=201)
def signup(
    payload: CredentialsRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> UserRead:
    """Create an account and sign it in. Each account gets its own keys and reviews."""
    if not get_settings().signup_enabled:
        raise HTTPException(status_code=403, detail="Sign-up is disabled on this deployment.")
    try:
        user = auth_service.create_user(db, payload.email, payload.password)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    token, _ = auth_service.issue_session(db, user)
    _set_session_cookie(response, request, token)
    return UserRead.from_row(user)


@router.post("/login", response_model=UserRead)
def login(
    payload: CredentialsRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> UserRead:
    user = auth_service.authenticate(db, payload.email, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    token, _ = auth_service.issue_session(db, user)
    _set_session_cookie(response, request, token)
    return UserRead.from_row(user)


@router.post("/logout", status_code=204)
def logout(
    request: Request, response: Response, db: Session = Depends(get_db)
) -> Response:
    auth_service.revoke_session(db, request.cookies.get(auth_service.SESSION_COOKIE))
    response.delete_cookie(auth_service.SESSION_COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/me", response_model=UserRead)
def read_me(user: CurrentUser) -> UserRead:
    return UserRead.from_row(user)
