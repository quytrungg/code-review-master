"""Claude sign-in: PKCE, the code exchange and access-token refresh.

The flow mirrors Claude Code's: the browser opens claude.ai, the operator approves, and the page
shows a code to paste back. The verifier never leaves the server — it waits in
`claude_oauth_states` — and the tokens land in `llm_keys` encrypted at rest like every other
credential.

Anthropic has no separate OAuth registration for third-party apps, so the client id, endpoints,
redirect URI and scopes default to Claude Code's public client and are settings. PKCE needs no
client secret, so there is no secret to store here.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import ensure_encryption_configured
from app.db.base import utcnow
from app.db.session import SessionLocal
from app.models.claude_oauth_state import ClaudeOAuthState
from app.models.keys import AUTH_OAUTH, LLM_CLAUDE, LLMKey

STATE_TTL_SECONDS = 15 * 60
REFRESH_SKEW_SECONDS = 120
# Anthropic sends `expires_in`; this only covers a response that omits it.
DEFAULT_TOKEN_LIFETIME_SECONDS = 3600
TOKEN_TIMEOUT_S = 20.0


class ClaudeOAuthError(Exception):
    """A sign-in step the operator can act on (bad code, expired state) or cannot (upstream)."""

    def __init__(self, detail: str, status_code: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: datetime


@dataclass(frozen=True)
class OAuthStart:
    authorize_url: str
    expires_at: datetime


# One lock per key row: two concurrent reviews must not spend the same refresh token twice.
_locks: dict[int, asyncio.Lock] = {}


def _lock(key_id: int) -> asyncio.Lock:
    return _locks.setdefault(key_id, asyncio.Lock())


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive UTC; PostgreSQL may hand back an aware value."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def pkce_pair() -> tuple[str, str]:
    """`(verifier, S256 challenge)` from RFC 7636, with a 64-character verifier."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorize_url(state: str, challenge: str) -> str:
    config = get_settings()
    query = urlencode(
        {
            "code": "true",
            "client_id": config.claude_oauth_client_id,
            "response_type": "code",
            "redirect_uri": config.claude_oauth_redirect_uri,
            "scope": config.claude_oauth_scopes,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    return f"{config.claude_oauth_authorize_url}?{query}"


def start(db: Session, user_id: int) -> OAuthStart:
    """Mint a state + verifier and return the URL the operator opens."""
    ensure_encryption_configured()
    now = utcnow()
    _reset_pending(db, user_id)
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    expires_at = now + timedelta(seconds=STATE_TTL_SECONDS)
    db.add(
        ClaudeOAuthState(user_id=user_id, state=state, verifier=verifier, expires_at=expires_at)
    )
    db.commit()
    return OAuthStart(authorize_url=authorize_url(state, challenge), expires_at=expires_at)


async def complete(db: Session, user_id: int, raw_code: str) -> LLMKey:
    """Exchange the pasted code for tokens and upsert this account's Claude sign-in key.

    The value claude.ai shows is `code#state`; a bare code is accepted too, because the state is
    already stored server-side. An echoed state must match the pending row, so a code copied from
    an older tab cannot silently replace the newest attempt.
    """
    code, _, echoed_state = (raw_code or "").strip().partition("#")
    code = code.strip()
    echoed_state = echoed_state.strip()
    if not code:
        raise ClaudeOAuthError("Paste the code Claude shows after approving the sign-in.")

    pending = _pending_state(db, user_id)
    if pending is None:
        raise ClaudeOAuthError("This sign-in has expired. Start the sign-in again.", 422)
    if echoed_state and echoed_state != pending.state:
        raise ClaudeOAuthError(
            "That code belongs to a different sign-in. Start again and paste the newest code.", 422
        )

    config = get_settings()
    body = await _post_token(
        {
            "grant_type": "authorization_code",
            "client_id": config.claude_oauth_client_id,
            "code": code,
            "state": pending.state,
            "redirect_uri": config.claude_oauth_redirect_uri,
            "code_verifier": pending.verifier,
        },
        purpose="sign-in",
    )
    tokens = _parse_tokens(body)
    db.delete(pending)
    key = _upsert(db, user_id, tokens)
    db.commit()
    db.refresh(key)
    return key


async def access_token(key: LLMKey) -> str:
    """The token to send now, refreshing an OAuth access token that is at or near expiry.

    The refresh commits in its own session: a caller's later rollback must not undo a rotated
    refresh token, which the provider has already invalidated. A failure here is the operator's to
    fix — the message points at Settings, never at the model.
    """
    if key.auth_type != AUTH_OAUTH:
        return key.api_key or ""
    if not _needs_refresh(key.expires_at):
        return key.api_key or ""

    async with _lock(key.id):
        with SessionLocal() as db:
            # Re-read under the lock: another task may have refreshed while this one waited.
            row = db.get(LLMKey, key.id)
            if row is None or row.auth_type != AUTH_OAUTH:
                raise ClaudeOAuthError(
                    "The Claude sign-in was removed. Sign in again in Settings.", 422
                )
            if not _needs_refresh(row.expires_at):
                return row.api_key or ""
            if not row.refresh_token:
                raise ClaudeOAuthError(
                    "The Claude sign-in has expired. Sign in again in Settings.", 422
                )
            body = await _post_token(
                {
                    "grant_type": "refresh_token",
                    "client_id": get_settings().claude_oauth_client_id,
                    "refresh_token": row.refresh_token,
                },
                purpose="refresh",
            )
            tokens = _parse_tokens(body)
            row.api_key = tokens.access_token
            if tokens.refresh_token:
                row.refresh_token = tokens.refresh_token
            row.expires_at = tokens.expires_at
            db.commit()
            return tokens.access_token


def _needs_refresh(expires_at: datetime | None) -> bool:
    stamp = _aware(expires_at)
    if stamp is None:
        return False
    return stamp <= utcnow() + timedelta(seconds=REFRESH_SKEW_SECONDS)


def _pending_state(db: Session, user_id: int) -> ClaudeOAuthState | None:
    """The newest pending sign-in for this account, or None when it is gone or expired."""
    row = db.scalars(
        select(ClaudeOAuthState)
        .where(ClaudeOAuthState.user_id == user_id)
        .order_by(ClaudeOAuthState.id.desc())
    ).first()
    if row is None:
        return None
    expires_at = _aware(row.expires_at)
    if expires_at is not None and expires_at <= utcnow():
        return None
    return row


def _reset_pending(db: Session, user_id: int) -> None:
    """One pending sign-in per account: starting again invalidates older attempts."""
    for row in db.scalars(
        select(ClaudeOAuthState).where(ClaudeOAuthState.user_id == user_id)
    ).all():
        db.delete(row)
    db.flush()


def _upsert(db: Session, user_id: int, tokens: TokenSet) -> LLMKey:
    """One Claude sign-in per account: reconnecting updates the row instead of adding a twin."""
    ensure_encryption_configured()
    key = db.scalars(
        select(LLMKey)
        .where(
            LLMKey.user_id == user_id,
            LLMKey.provider == LLM_CLAUDE,
            LLMKey.auth_type == AUTH_OAUTH,
        )
        .order_by(LLMKey.id)
    ).first()
    if key is None:
        key = LLMKey(
            user_id=user_id,
            provider=LLM_CLAUDE,
            auth_type=AUTH_OAUTH,
            label="Claude sign-in",
        )
        db.add(key)
    key.api_key = tokens.access_token
    if tokens.refresh_token:
        # A refresh response may omit the refresh token; keep the one that still works.
        key.refresh_token = tokens.refresh_token
    key.expires_at = tokens.expires_at
    return key


async def _post_token(payload: dict, *, purpose: str) -> dict:
    """POST to the token endpoint; mapping every failure onto what the operator should do next."""
    config = get_settings()
    try:
        async with httpx.AsyncClient(timeout=TOKEN_TIMEOUT_S) as client:
            response = await client.post(
                config.claude_oauth_token_url,
                json=payload,
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise ClaudeOAuthError(
            f"Could not reach Claude to {purpose} ({exc.__class__.__name__}). Try again.", 502
        ) from exc

    if response.status_code in (400, 401, 403):
        if purpose == "refresh":
            raise ClaudeOAuthError(
                "Claude no longer accepts the saved sign-in. Sign in again in Settings.", 422
            )
        raise ClaudeOAuthError(
            "Claude did not accept this code. Start the sign-in again and paste the new code.", 422
        )
    if response.status_code != 200:
        raise ClaudeOAuthError(
            f"Claude returned HTTP {response.status_code} while trying to {purpose}. Try again.",
            502,
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise ClaudeOAuthError("Claude returned an unreadable token response.", 502) from exc
    if not isinstance(body, dict):
        raise ClaudeOAuthError("Claude returned an unreadable token response.", 502)
    return body


def _parse_tokens(body: dict) -> TokenSet:
    access = body.get("access_token")
    if not isinstance(access, str) or not access.strip():
        raise ClaudeOAuthError("Claude did not return an access token. Try the sign-in again.", 502)
    refresh = body.get("refresh_token")
    expires_in = body.get("expires_in")
    lifetime = (
        expires_in
        if isinstance(expires_in, int) and not isinstance(expires_in, bool) and expires_in > 0
        else DEFAULT_TOKEN_LIFETIME_SECONDS
    )
    return TokenSet(
        access_token=access.strip(),
        refresh_token=refresh.strip() if isinstance(refresh, str) and refresh.strip() else None,
        expires_at=utcnow() + timedelta(seconds=lifetime),
    )
