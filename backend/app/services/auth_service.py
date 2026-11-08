"""Password hashing, account creation and cookie-backed sessions."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User, UserSession

logger = logging.getLogger(__name__)

SESSION_COOKIE = "acr_session"
SESSION_DAYS = 14
PBKDF2_ITERATIONS = 260_000
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
EMAIL_PATTERN = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(?:\.[^@\s.]+)+$")
MAX_EMAIL_LENGTH = 254

_ALGORITHM = "pbkdf2_sha256"


class AuthError(Exception):
    """Account problem the operator can act on (duplicate email, bad input, bad credentials)."""

    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def normalise_email(email: str) -> str:
    value = (email or "").strip().lower()
    if len(value) > MAX_EMAIL_LENGTH or not EMAIL_PATTERN.match(value):
        raise AuthError("Enter a valid email address.", 422)
    return value


def _validate_password(password: str) -> str:
    value = password or ""
    if len(value) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Use at least {MIN_PASSWORD_LENGTH} characters for the password.", 422)
    if len(value) > MAX_PASSWORD_LENGTH:
        raise AuthError(f"Passwords are limited to {MAX_PASSWORD_LENGTH} characters.", 422)
    return value


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{_ALGORITHM}${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time verification; a malformed or placeholder hash never matches."""
    if not stored or not password:
        return False
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$", 3)
        if algorithm != _ALGORITHM:
            return False
        expected = bytes.fromhex(digest_hex)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


def create_user(db: Session, email: str, password: str) -> User:
    address = normalise_email(email)
    secret = _validate_password(password)
    if db.scalars(select(User).where(User.email == address)).first() is not None:
        raise AuthError("That email already has an account.", 409)
    user = User(email=address, password_hash=hash_password(secret))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    address = (email or "").strip().lower()
    user = db.scalars(select(User).where(User.email == address)).first()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_session(db: Session, user: User) -> tuple[str, UserSession]:
    token = secrets.token_urlsafe(32)
    session = UserSession(
        user_id=user.id,
        token_hash=_hash_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return token, session


def resolve_session(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    session = db.scalars(
        select(UserSession).where(UserSession.token_hash == _hash_token(token))
    ).first()
    if session is None:
        return None
    expires_at = session.expires_at
    if expires_at.tzinfo is None:  # SQLite hands back naive UTC
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        db.delete(session)
        db.commit()
        return None
    return db.get(User, session.user_id)


def revoke_session(db: Session, token: str | None) -> None:
    if not token:
        return
    session = db.scalars(
        select(UserSession).where(UserSession.token_hash == _hash_token(token))
    ).first()
    if session is not None:
        db.delete(session)
        db.commit()
