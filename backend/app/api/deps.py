from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.services import auth_service

__all__ = ["CurrentUser", "get_current_user", "get_db"]


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The signed-in account, resolved from the session cookie.

    Every non-public router depends on this, so a missing or expired session is a `401` before
    any handler body runs. Routes that need the owner take `user: CurrentUser` and get the same
    instance — FastAPI caches the dependency for the duration of the request.
    """
    user = auth_service.resolve_session(db, request.cookies.get(auth_service.SESSION_COOKIE))
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Sign in to continue.",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
