"""Credential encryption at rest (phase 16).

The suite shares one SQLite database and one fixed test key (see `conftest.py`). Every key this
module creates is tagged with `LABEL` and deleted afterwards, so later modules see the same
credential state they did before.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.db.encryption import encrypt_plaintext, plaintext_count, reencrypt_all
from app.db.session import SessionLocal
from app.services import keys_service
from tests.conftest import TEST_EMAIL

TOKEN = "ghp_0123456789abcdefghijklmnopqrstuvwxyz"
API_KEY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz"
LABEL = "enc-test"
TEST_KEY = "jViGHKfT9myHM70vzMgtTdVw7CsWitgWA-xXhDnLZLg="
OTHER_KEY = "sW2cX2ReACUEGGc13zGVjyPZbp1gWAjx-r96TnLy1Vw="

_CREATED: list[tuple[str, int]] = []


# --------------------------------------------------------------------------------- helpers


def _user_id() -> int:
    with SessionLocal() as db:
        return int(
            db.execute(
                text("SELECT id FROM users WHERE email = :email"), {"email": TEST_EMAIL}
            ).scalar_one()
        )


def _raw(table: str, column: str, row_id: int) -> str | None:
    with SessionLocal() as db:
        return db.execute(
            text(f"SELECT {column} FROM {table} WHERE id = :id"), {"id": row_id}
        ).scalar_one()


def _create_vcs(client, token: str = TOKEN) -> dict:
    response = client.post(
        "/api/keys/version-control",
        json={"provider": "github", "token": token, "label": LABEL},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    _CREATED.append(("version_control_keys", body["id"]))
    return body


def _create_llm(client, api_key: str = API_KEY) -> dict:
    response = client.post(
        "/api/keys/llm", json={"provider": "claude", "api_key": api_key, "label": LABEL}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    _CREATED.append(("llm_keys", body["id"]))
    return body


@pytest.fixture(autouse=True)
def _cleanup(client):
    yield
    with SessionLocal() as db:
        for table, row_id in _CREATED:
            db.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_id})
        db.commit()
    _CREATED.clear()
    get_settings.cache_clear()


# ----------------------------------------------------------------------------------- tests


def test_token_is_ciphertext_at_rest(client):
    created = _create_vcs(client)

    stored = _raw("version_control_keys", "token", created["id"])
    assert stored.startswith("enc:v1:")
    assert TOKEN not in stored
    assert "ghp_" not in stored

    # The wire contract is unchanged: mask by default, raw only on request.
    assert created["token"] is None
    assert created["token_masked"] == "ghp_" + "•" * 8 + "wxyz"


def test_reveal_returns_the_exact_secret(client):
    created = _create_vcs(client)
    revealed = {
        row["id"]: row
        for row in client.get("/api/keys/version-control", params={"reveal": "true"}).json()
    }
    assert revealed[created["id"]]["token"] == TOKEN

    client.put("/api/settings", json={"version_control_key_id": created["id"]})
    settings = client.get("/api/settings", params={"reveal": "true"}).json()
    assert settings["version_control_token"] == TOKEN
    assert settings["version_control"]["secret_masked"] == "ghp_" + "•" * 8 + "wxyz"


def test_equal_secrets_produce_different_ciphertext(client):
    first = _create_vcs(client)
    second = _create_vcs(client)
    assert _raw("version_control_keys", "token", first["id"]) != _raw(
        "version_control_keys", "token", second["id"]
    )


def test_orm_reads_plaintext(client):
    created = _create_vcs(client)
    with SessionLocal() as db:
        row = keys_service.get_version_control(db, _user_id(), created["id"])
        assert row.token == TOKEN


def test_legacy_plaintext_row_is_readable_then_encrypted(client):
    with SessionLocal() as db:
        db.execute(
            text(
                "INSERT INTO llm_keys (user_id, provider, api_key, label, created_at, updated_at) "
                "VALUES (:user_id, 'claude', :api_key, :label, :ts, :ts)"
            ),
            {
                "user_id": _user_id(),
                "api_key": API_KEY,
                "label": LABEL,
                "ts": datetime.now(timezone.utc),
            },
        )
        db.commit()
        legacy_id = int(db.execute(text("SELECT MAX(id) FROM llm_keys")).scalar_one())
    _CREATED.append(("llm_keys", legacy_id))

    # A backup made before 0011 still opens, so the app is not bricked by the upgrade.
    revealed = {
        row["id"]: row for row in client.get("/api/keys/llm", params={"reveal": "true"}).json()
    }
    assert revealed[legacy_id]["api_key"] == API_KEY
    with SessionLocal() as db:
        assert plaintext_count(db.connection()) >= 1

    with SessionLocal() as db:
        counts = encrypt_plaintext(db.connection())
        db.commit()
    assert counts["llm_keys"] >= 1
    assert _raw("llm_keys", "api_key", legacy_id).startswith("enc:v1:")
    with SessionLocal() as db:
        assert plaintext_count(db.connection()) == 0

    revealed = {
        row["id"]: row for row in client.get("/api/keys/llm", params={"reveal": "true"}).json()
    }
    assert revealed[legacy_id]["api_key"] == API_KEY


def test_missing_key_blocks_writes(client, monkeypatch):
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", "")
    get_settings.cache_clear()

    with SessionLocal() as db:
        before = db.execute(text("SELECT COUNT(*) FROM version_control_keys")).scalar_one()

    response = client.post(
        "/api/keys/version-control", json={"provider": "github", "token": TOKEN}
    )
    assert response.status_code == 503, response.text
    assert "CREDENTIALS_ENCRYPTION_KEY" in response.json()["detail"]

    with SessionLocal() as db:
        after = db.execute(text("SELECT COUNT(*) FROM version_control_keys")).scalar_one()
    assert after == before


def test_wrong_key_blocks_reads(client, monkeypatch):
    created = _create_vcs(client)
    client.put("/api/settings", json={"version_control_key_id": created["id"]})

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", OTHER_KEY)
    get_settings.cache_clear()

    for path in ("/api/keys/version-control?reveal=true", "/api/settings?reveal=true"):
        response = client.get(path)
        assert response.status_code == 503, (path, response.text)
        assert response.json()["detail"] == (
            "Stored credentials cannot be decrypted with the configured key."
        )
        assert "enc:v1:" not in response.text

    # The API stays up: this is a configuration state, not a crash.
    assert client.get("/api/health").status_code == 200


def test_rotation_rewrites_every_row(client, monkeypatch):
    vcs = _create_vcs(client)
    llm = _create_llm(client)
    before = _raw("version_control_keys", "token", vcs["id"])

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", f"{OTHER_KEY},{TEST_KEY}")
    get_settings.cache_clear()
    with SessionLocal() as db:
        counts = reencrypt_all(db.connection())
        db.commit()
    assert counts["version_control_keys"] >= 1 and counts["llm_keys"] >= 1

    # Dropping the old key after rotation leaves every row readable.
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", OTHER_KEY)
    get_settings.cache_clear()

    assert _raw("version_control_keys", "token", vcs["id"]) != before
    revealed = {
        row["id"]: row
        for row in client.get("/api/keys/version-control", params={"reveal": "true"}).json()
    }
    assert revealed[vcs["id"]]["token"] == TOKEN
    llm_revealed = {
        row["id"]: row for row in client.get("/api/keys/llm", params={"reveal": "true"}).json()
    }
    assert llm_revealed[llm["id"]]["api_key"] == API_KEY

    # The suite shares its database with earlier modules, so leave every row keyed with the
    # suite key again instead of stranding their credentials on the rotation key.
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", f"{TEST_KEY},{OTHER_KEY}")
    get_settings.cache_clear()
    with SessionLocal() as db:
        reencrypt_all(db.connection())
        db.commit()


def test_secrets_never_appear_in_logs(client, caplog):
    caplog.set_level(logging.DEBUG)
    created = _create_vcs(client)
    client.get("/api/keys/version-control")
    client.get("/api/keys/version-control", params={"reveal": "true"})
    client.get("/api/settings", params={"reveal": "true"})

    stored = _raw("version_control_keys", "token", created["id"])
    assert TOKEN not in caplog.text
    assert stored not in caplog.text
    assert "enc:v1:" not in caplog.text
