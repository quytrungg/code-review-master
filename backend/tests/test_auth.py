from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.user import UserSession
from app.services.auth_service import hash_password, verify_password

PASSWORD = "correct-horse-battery"


def _signup(client, email="fresh@example.com", password=PASSWORD):
    return client.post("/api/auth/signup", json={"email": email, "password": password})


def test_password_hashing_roundtrip():
    stored = hash_password("hunter2hunter2")
    assert stored.startswith("pbkdf2_sha256$")
    assert "hunter2hunter2" not in stored
    assert verify_password("hunter2hunter2", stored) is True
    assert verify_password("wrong-password", stored) is False
    assert verify_password("hunter2hunter2", "!") is False
    assert verify_password("hunter2hunter2", None) is False


def test_signup_creates_a_session_and_returns_the_account(anon_client):
    response = _signup(anon_client, "  SignUp@Example.COM ")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "signup@example.com"
    assert body["id"] > 0
    assert body["created_at"].endswith("Z")
    assert "acr_session" in anon_client.cookies

    me = anon_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "signup@example.com"


def test_signup_rejects_duplicates_weak_passwords_and_bad_emails(anon_client):
    assert _signup(anon_client, "dup@example.com").status_code == 201

    duplicate = _signup(anon_client, "DUP@example.com")
    assert duplicate.status_code == 409
    assert "already has an account" in duplicate.json()["detail"]

    weak = _signup(anon_client, "weak@example.com", password="short")
    assert weak.status_code == 422
    assert "at least 8 characters" in weak.json()["detail"]

    for bad in ("nope", "no@tld", "two@@example.com", ""):
        response = _signup(anon_client, bad)
        assert response.status_code == 422, (bad, response.text)


def test_login_rejects_a_wrong_password_and_accepts_the_right_one(anon_client):
    _signup(anon_client, "login@example.com")
    anon_client.cookies.clear()

    wrong = anon_client.post(
        "/api/auth/login", json={"email": "login@example.com", "password": "not-the-password"}
    )
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "Email or password is incorrect."

    unknown = anon_client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    assert unknown.status_code == 401

    good = anon_client.post(
        "/api/auth/login", json={"email": "LOGIN@example.com", "password": PASSWORD}
    )
    assert good.status_code == 200
    assert good.json()["email"] == "login@example.com"
    assert anon_client.get("/api/auth/me").status_code == 200


def test_logout_revokes_the_session(anon_client):
    _signup(anon_client, "logout@example.com")
    assert anon_client.get("/api/auth/me").status_code == 200

    out = anon_client.post("/api/auth/logout")
    assert out.status_code == 204
    assert anon_client.get("/api/auth/me").status_code == 401
    assert anon_client.get("/api/reviews").status_code == 401


def test_every_private_route_requires_a_session(anon_client):
    for path in ("/api/settings", "/api/keys/llm", "/api/keys/version-control", "/api/reviews", "/api/models"):
        response = anon_client.get(path)
        assert response.status_code == 401, path
        assert response.json()["detail"] == "Sign in to continue."
        assert response.headers["www-authenticate"] == "Cookie"


def test_sessions_are_stored_as_hashes_not_tokens(anon_client):
    _signup(anon_client, "hash@example.com")
    token = anon_client.cookies["acr_session"]

    db = SessionLocal()
    try:
        rows = list(db.scalars(select(UserSession)))
        assert rows, "a session row should exist"
        assert all(row.token_hash != token for row in rows)
        assert len(rows[-1].token_hash) == 64  # sha256 hex
    finally:
        db.close()


def test_an_expired_session_is_rejected_and_cleaned_up(anon_client):
    import hashlib

    _signup(anon_client, "expired@example.com")
    token = anon_client.cookies["acr_session"]
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()

    db = SessionLocal()
    try:
        session = db.scalars(
            select(UserSession).where(UserSession.token_hash == digest)
        ).one()
        session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        session_id = session.id
    finally:
        db.close()

    assert anon_client.get("/api/auth/me").status_code == 401

    db = SessionLocal()
    try:
        assert db.get(UserSession, session_id) is None, "expired rows are deleted on sight"
    finally:
        db.close()
