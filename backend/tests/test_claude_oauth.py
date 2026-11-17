"""Claude sign-in: PKCE, the code exchange, refresh and the bearer transport."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.db.base import utcnow
from app.db.encryption import reencrypt_all
from app.db.session import SessionLocal
from app.models.claude_oauth_state import ClaudeOAuthState
from app.models.keys import AUTH_OAUTH, LLM_CLAUDE, LLMKey
from app.models.llm_call import LLMPurpose
from app.services import claude_oauth_service, keys_service, llm_service
from tests.conftest import TEST_EMAIL

_EXTRA_KEYS: list[int] = []


def _user_id() -> int:
    with SessionLocal() as db:
        return int(
            db.execute(
                text("SELECT id FROM users WHERE email = :email"), {"email": TEST_EMAIL}
            ).scalar_one()
        )


def _oauth_keys() -> list[LLMKey]:
    with SessionLocal() as db:
        return list(
            db.query(LLMKey)
            .filter(LLMKey.provider == LLM_CLAUDE, LLMKey.auth_type == AUTH_OAUTH)
            .order_by(LLMKey.id)
        )


def _pending_state() -> tuple[str, str]:
    """The stored `(state, verifier)` for the newest pending sign-in."""
    with SessionLocal() as db:
        row = (
            db.query(ClaudeOAuthState)
            .order_by(ClaudeOAuthState.id.desc())
            .first()
        )
        assert row is not None, "the start endpoint stored no state"
        return row.state, row.verifier


def _seed_oauth_key(*, expires_in_seconds: int) -> int:
    with SessionLocal() as db:
        key = LLMKey(
            user_id=_user_id(),
            provider=LLM_CLAUDE,
            auth_type=AUTH_OAUTH,
            api_key="old-access",
            refresh_token="old-refresh",
            expires_at=utcnow() + timedelta(seconds=expires_in_seconds),
        )
        db.add(key)
        db.commit()
        return key.id


@pytest.fixture(autouse=True)
def _cleanup(client):
    yield
    with SessionLocal() as db:
        db.query(ClaudeOAuthState).delete()
        db.query(LLMKey).filter(
            LLMKey.provider == LLM_CLAUDE, LLMKey.auth_type == AUTH_OAUTH
        ).delete()
        for key_id in _EXTRA_KEYS:
            db.query(LLMKey).filter(LLMKey.id == key_id).delete()
        db.commit()
    _EXTRA_KEYS.clear()


def _token_stub(monkeypatch, responses: list[dict], calls: list[dict] | None = None):
    remaining = list(responses)

    async def post(payload, *, purpose):
        if calls is not None:
            calls.append({"payload": payload, "purpose": purpose})
        return remaining.pop(0)

    monkeypatch.setattr(claude_oauth_service, "_post_token", post)


# ------------------------------------------------------------------------------------ start


def test_start_returns_an_s256_authorize_url(client):
    response = client.post("/api/keys/claude/oauth/start")
    assert response.status_code == 200, response.text
    body = response.json()

    parsed = urlparse(body["authorize_url"])
    query = parse_qs(parsed.query)
    config = get_settings()
    assert parsed.scheme == "https"
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["client_id"] == [config.claude_oauth_client_id]
    assert query["redirect_uri"] == [config.claude_oauth_redirect_uri]
    assert query["scope"] == [config.claude_oauth_scopes]
    assert body["expires_at"] is not None

    state, verifier = _pending_state()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert query["code_challenge"] == [expected]
    assert query["state"] == [state]
    assert query["code_challenge"] != [verifier]


# --------------------------------------------------------------------------------- complete


def test_complete_exchanges_the_code_for_an_encrypted_key(client, monkeypatch):
    calls: list[dict] = []
    _token_stub(
        monkeypatch,
        [
            {
                "access_token": "oauth-access-1",
                "refresh_token": "oauth-refresh-1",
                "expires_in": 3600,
            }
        ],
        calls,
    )

    client.post("/api/keys/claude/oauth/start")
    state, verifier = _pending_state()
    response = client.post(
        "/api/keys/claude/oauth/complete", json={"code": f"the-code#{state}"}
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["provider"] == "claude"
    assert body["auth_type"] == "oauth"
    assert body["has_refresh_token"] is True
    assert body["expires_at"] is not None
    assert body["api_key"] is None
    assert "oauth-access-1" not in (body["api_key_masked"] or "")

    assert calls[0]["purpose"] == "sign-in"
    assert calls[0]["payload"]["grant_type"] == "authorization_code"
    assert calls[0]["payload"]["code"] == "the-code"
    assert calls[0]["payload"]["state"] == state
    assert calls[0]["payload"]["code_verifier"] == verifier

    keys = _oauth_keys()
    assert len(keys) == 1
    assert keys[0].api_key == "oauth-access-1"
    assert keys[0].refresh_token == "oauth-refresh-1"

    # No row was consumed twice and both secrets are ciphertext on disk.
    with SessionLocal() as db:
        assert db.query(ClaudeOAuthState).count() == 0
        stored = db.execute(
            text("SELECT api_key, refresh_token FROM llm_keys WHERE id = :id"),
            {"id": keys[0].id},
        ).one()
        assert stored.api_key.startswith("enc:v1:")
        assert stored.refresh_token.startswith("enc:v1:")


def test_a_second_sign_in_updates_the_same_key(client, monkeypatch):
    _token_stub(
        monkeypatch,
        [
            {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600},
            {"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 3600},
        ],
    )

    client.post("/api/keys/claude/oauth/start")
    first = client.post("/api/keys/claude/oauth/complete", json={"code": "one"}).json()
    client.post("/api/keys/claude/oauth/start")
    second = client.post("/api/keys/claude/oauth/complete", json={"code": "two"}).json()

    assert first["id"] == second["id"]
    keys = _oauth_keys()
    assert len(keys) == 1
    assert keys[0].api_key == "access-2"
    assert keys[0].refresh_token == "refresh-2"


def test_an_unknown_or_expired_state_is_rejected(client):
    response = client.post("/api/keys/claude/oauth/complete", json={"code": "the-code#nope"})
    assert response.status_code == 422
    assert "expired" in response.json()["detail"]
    assert _oauth_keys() == []


def test_a_code_from_another_sign_in_is_rejected(client):
    client.post("/api/keys/claude/oauth/start")
    response = client.post(
        "/api/keys/claude/oauth/complete", json={"code": "the-code#not-the-pending-state"}
    )
    assert response.status_code == 422
    assert "different sign-in" in response.json()["detail"]
    assert _oauth_keys() == []


# ------------------------------------------------------------------------------------ refresh


def test_an_expiring_sign_in_refreshes_before_use(client, monkeypatch):
    key_id = _seed_oauth_key(expires_in_seconds=-60)
    calls: list[dict] = []
    _token_stub(
        monkeypatch,
        [
            {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 7200,
            }
        ],
        calls,
    )

    with SessionLocal() as db:
        key = db.get(LLMKey, key_id)
        assert asyncio.run(keys_service.access_token_for(key)) == "new-access"

    assert calls[0]["purpose"] == "refresh"
    assert calls[0]["payload"]["grant_type"] == "refresh_token"
    assert calls[0]["payload"]["refresh_token"] == "old-refresh"

    with SessionLocal() as db:
        stored = db.get(LLMKey, key_id)
        assert stored.api_key == "new-access"
        assert stored.refresh_token == "new-refresh"


def test_a_fresh_sign_in_is_not_refreshed(client, monkeypatch):
    key_id = _seed_oauth_key(expires_in_seconds=3600)
    calls: list[dict] = []
    _token_stub(monkeypatch, [], calls)

    with SessionLocal() as db:
        key = db.get(LLMKey, key_id)
        assert asyncio.run(keys_service.access_token_for(key)) == "old-access"

    assert calls == []


def test_a_rejected_refresh_names_settings_and_keeps_the_old_token(client, monkeypatch):
    key_id = _seed_oauth_key(expires_in_seconds=-60)

    async def reject(payload, *, purpose):
        raise claude_oauth_service.ClaudeOAuthError(
            "Claude no longer accepts the saved sign-in. Sign in again in Settings.", 422
        )

    monkeypatch.setattr(claude_oauth_service, "_post_token", reject)

    with SessionLocal() as db:
        key = db.get(LLMKey, key_id)
        with pytest.raises(keys_service.KeyError) as raised:
            asyncio.run(keys_service.access_token_for(key))
    assert raised.value.status_code == 422
    assert "Settings" in raised.value.detail

    with SessionLocal() as db:
        assert db.get(LLMKey, key_id).api_key == "old-access"


# ---------------------------------------------------------------------------------- transport


def test_oauth_generate_sends_bearer_beta_and_the_claude_code_preamble(client, monkeypatch):
    captured: dict = {}

    async def post(url, headers, payload, timeout=None):
        captured.update(url=url, headers=headers, payload=payload)
        return {
            "content": [{"type": "text", "text": "looks fine"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 31, "output_tokens": 7},
        }

    monkeypatch.setattr(llm_service, "_post_claude_messages", post)

    credentials = llm_service.LLMCredentials(
        provider=LLM_CLAUDE, api_key="oauth-access", base_url=None, auth_type=AUTH_OAUTH
    )
    result = asyncio.run(
        llm_service.generate(
            credentials,
            llm_service.parse_model_id("claude:claude-sonnet-4-5-20250929"),
            "SYSTEM",
            "USER",
            purpose=LLMPurpose.INGEST,
        )
    )

    assert result.text == "looks fine"
    assert result.prompt_tokens == 31
    assert result.completion_tokens == 7
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["Authorization"] == "Bearer oauth-access"
    assert captured["headers"]["anthropic-beta"] == llm_service.CLAUDE_OAUTH_BETA
    assert captured["headers"]["anthropic-version"] == llm_service.ANTHROPIC_VERSION
    system = captured["payload"]["system"]
    assert system[0] == {"type": "text", "text": llm_service.CLAUDE_CODE_PREAMBLE}
    assert system[1] == {"type": "text", "text": "SYSTEM"}
    assert captured["payload"]["messages"] == [{"role": "user", "content": "USER"}]


def test_the_claude_code_preamble_is_its_own_system_block():
    assert llm_service.claude_system_prompt("SYSTEM", oauth=False) == "SYSTEM"
    assert llm_service.claude_system_prompt("SYSTEM", oauth=True) == [
        {"type": "text", "text": llm_service.CLAUDE_CODE_PREAMBLE},
        {"type": "text", "text": "SYSTEM"},
    ]
    # An empty app prompt is still the one-block form; OAuth needs the preamble block itself.
    assert llm_service.claude_system_prompt("", oauth=True) == [
        {"type": "text", "text": llm_service.CLAUDE_CODE_PREAMBLE}
    ]


def _catalogue(monkeypatch, ids: list[str]) -> None:
    async def models(*args, **kwargs):
        return [{"id": model_id, "label": model_id} for model_id in ids]

    monkeypatch.setattr(llm_service, "list_claude_models", models)


def test_probe_skips_a_model_the_catalogue_lists_but_messages_rejects(client, monkeypatch):
    """A subscription can 404 a stale catalogue entry; that is not a failed sign-in."""
    calls: list[str] = []

    async def post(url, headers, payload, timeout=None):
        calls.append(payload["model"])
        if payload["model"] == "claude-sonnet-4-5-20250929":
            raise llm_service.LLMError("Claude does not have the model", 404)
        return {"content": [], "stop_reason": "max_tokens", "usage": {}}

    monkeypatch.setattr(llm_service, "_post_claude_messages", post)
    _catalogue(monkeypatch, ["claude-sonnet-4-5-20250929", "claude-fable-5-2"])

    ok, detail, metadata = asyncio.run(llm_service.probe_claude_oauth("token"))
    assert ok is True
    assert metadata == {"model": "claude-fable-5-2"}
    assert calls == ["claude-sonnet-4-5-20250929", "claude-fable-5-2"]
    assert "claude-fable-5-2" in detail


def test_probe_prefers_the_configured_model(client, monkeypatch):
    calls: list[str] = []

    async def post(url, headers, payload, timeout=None):
        calls.append(payload["model"])
        return {"content": [], "stop_reason": "max_tokens", "usage": {}}

    monkeypatch.setattr(llm_service, "_post_claude_messages", post)
    _catalogue(monkeypatch, ["catalogue-model"])

    ok, _, metadata = asyncio.run(
        llm_service.probe_claude_oauth("token", model="configured-model")
    )
    assert ok is True
    assert calls == ["configured-model"]
    assert metadata == {"model": "configured-model"}


def test_probe_reports_a_rejected_sign_in(client, monkeypatch):
    async def post(url, headers, payload, timeout=None):
        raise llm_service.LLMError("Claude rejected the sign-in. Sign in again in Settings.", 401)

    monkeypatch.setattr(llm_service, "_post_claude_messages", post)
    _catalogue(monkeypatch, ["m1", "m2"])

    ok, detail, _ = asyncio.run(llm_service.probe_claude_oauth("token"))
    assert ok is False
    assert "rejected the sign-in" in detail


def test_probe_fails_cleanly_when_every_model_is_rejected(client, monkeypatch):
    async def post(url, headers, payload, timeout=None):
        raise llm_service.LLMError("model gone", 404)

    monkeypatch.setattr(llm_service, "_post_claude_messages", post)
    _catalogue(monkeypatch, ["m1"])

    ok, detail, _ = asyncio.run(llm_service.probe_claude_oauth("token"))
    assert ok is False
    assert "Pick another model" in detail


# ------------------------------------------------------------------------------ temperature


def test_claude_payloads_never_send_temperature():
    """Newer Claude models reject `temperature`, and the catalogue has no capability flag."""
    for model in ("claude-opus-5-5", "claude-sonnet-4-6"):
        for oauth in (True, False):
            payload = llm_service.claude_message_payload(model, "s", "u", 5, oauth=oauth)
            assert "temperature" not in payload


def test_the_model_catalogue_drops_deprecated_entries(client):
    payload = {
        "data": [
            {
                "id": "claude-sonnet-4-5-20250929",
                "display_name": "Claude Sonnet 4.5",
                "lifecycle": "deprecated",
                "deprecated_at": "2026-09-30T18:30:00Z",
            },
            {"id": "claude-sonnet-5-5", "display_name": "Claude Sonnet 5.5", "lifecycle": "active"},
        ]
    }
    assert llm_service._claude_catalogue(payload) == [
        {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5"}
    ]

    only_deprecated = {"data": [payload["data"][0]]}
    assert llm_service._claude_catalogue(only_deprecated) == [
        {"id": "claude-sonnet-4-5-20250929", "label": "Claude Sonnet 4.5"}
    ]


# ------------------------------------------------------------------------------------- reveal


def test_reveal_never_returns_the_refresh_token(client, monkeypatch):
    _token_stub(
        monkeypatch,
        [{"access_token": "oauth-access-1", "refresh_token": "oauth-refresh-1", "expires_in": 60}],
    )
    client.post("/api/keys/claude/oauth/start")
    client.post("/api/keys/claude/oauth/complete", json={"code": "the-code"})

    rows = client.get("/api/keys/llm?reveal=true").json()
    row = next(item for item in rows if item["auth_type"] == "oauth")
    assert row["api_key"] == "oauth-access-1"
    assert "refresh_token" not in row
    assert row["has_refresh_token"] is True


def test_an_api_key_row_still_reports_api_key_auth(client):
    created = client.post(
        "/api/keys/llm", json={"provider": "claude", "api_key": "sk-ant-api03-test-123456"}
    )
    assert created.status_code == 201, created.text
    _EXTRA_KEYS.append(created.json()["id"])
    assert created.json()["auth_type"] == "api_key"
    assert created.json()["has_refresh_token"] is False
    assert created.json()["expires_at"] is None


TEST_KEY = "jViGHKfT9myHM70vzMgtTdVw7CsWitgWA-xXhDnLZLg="
OTHER_KEY = "sW2cX2ReACUEGGc13zGVjyPZbp1gWAjx-r96TnLy1Vw="


def test_key_rotation_rewrites_the_refresh_token_and_pending_verifier(client, monkeypatch):
    """A rotated encryption key must not strand the secrets that have no reveal path."""
    key_id = _seed_oauth_key(expires_in_seconds=3600)
    with SessionLocal() as db:
        db.add(
            ClaudeOAuthState(
                user_id=_user_id(),
                state="rotation-state",
                verifier="rotation-verifier",
                expires_at=utcnow() + timedelta(minutes=5),
            )
        )
        db.commit()
    try:
        monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", f"{OTHER_KEY},{TEST_KEY}")
        get_settings.cache_clear()
        with SessionLocal() as db:
            counts = reencrypt_all(db.connection())
            db.commit()
        assert counts["llm_keys.refresh_token"] >= 1
        assert counts["claude_oauth_states.verifier"] >= 1

        # Dropping the old key leaves both readable through the ORM.
        monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", OTHER_KEY)
        get_settings.cache_clear()
        with SessionLocal() as db:
            assert db.get(LLMKey, key_id).refresh_token == "old-refresh"
            state = db.query(ClaudeOAuthState).filter_by(state="rotation-state").one()
            assert state.verifier == "rotation-verifier"
    finally:
        # The suite shares its database: leave every row keyed with the suite key again.
        monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", f"{TEST_KEY},{OTHER_KEY}")
        get_settings.cache_clear()
        with SessionLocal() as db:
            reencrypt_all(db.connection())
            db.commit()
        monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", TEST_KEY)
        get_settings.cache_clear()
