"""Phase 35 — Beta features: registry, per-user storage, API contract."""

from __future__ import annotations

from app.db.session import SessionLocal
from app.services import settings_service


def _user_id(client) -> int:
    me = client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    return me.json()["id"]


def test_fresh_account_reads_the_flag_off_with_the_registry(client):
    body = client.get("/api/settings").json()
    assert body["beta_features"] == {"push_back_lessons": False}
    assert body["beta_registry"] == [
        {
            "id": "push_back_lessons",
            "label": "Push-back lessons",
            "description": (
                "When you push back on a finding, offer to record the lesson "
                "as a rule in a skill foundation."
            ),
        }
    ]


def test_put_persists_the_flag_for_that_account(client):
    updated = client.put("/api/settings", json={"beta_features": {"push_back_lessons": True}})
    assert updated.status_code == 200, updated.text
    assert updated.json()["beta_features"]["push_back_lessons"] is True

    # A plain GET reads the stored value back, not the PUT echo.
    body = client.get("/api/settings").json()
    assert body["beta_features"]["push_back_lessons"] is True


def test_two_accounts_flags_are_isolated(client, second_client):
    on = client.put("/api/settings", json={"beta_features": {"push_back_lessons": True}})
    assert on.status_code == 200

    other = second_client.get("/api/settings").json()
    assert other["beta_features"]["push_back_lessons"] is False

    # The second account flipping its own flag never touches the first.
    flipped = second_client.put("/api/settings", json={"beta_features": {"push_back_lessons": True}})
    assert flipped.status_code == 200
    assert client.get("/api/settings").json()["beta_features"]["push_back_lessons"] is True


def test_unknown_flag_id_is_422_and_persists_nothing(client):
    client.put("/api/settings", json={"beta_features": {"push_back_lessons": True}})

    rejected = client.put(
        "/api/settings",
        json={"beta_features": {"push_back_lessons": False, "time_travel": True}},
    )
    assert rejected.status_code == 422
    assert "time_travel" in rejected.json()["detail"]

    # The whole dict was refused, so the previous value survives untouched.
    body = client.get("/api/settings").json()
    assert body["beta_features"] == {"push_back_lessons": True}


def test_omitting_beta_features_leaves_flags_unchanged(client):
    client.put("/api/settings", json={"beta_features": {"push_back_lessons": True}})

    # Unrelated field only — beta_features is absent from the payload.
    untouched = client.put("/api/settings", json={"monthly_token_budget": 1000})
    assert untouched.status_code == 200
    assert untouched.json()["beta_features"]["push_back_lessons"] is True


def test_explicit_null_clears_every_flag(client):
    client.put("/api/settings", json={"beta_features": {"push_back_lessons": True}})

    cleared = client.put("/api/settings", json={"beta_features": None})
    assert cleared.status_code == 200
    assert cleared.json()["beta_features"] == {"push_back_lessons": False}


def test_beta_enabled_reads_the_service_gate(client):
    user_id = _user_id(client)
    db = SessionLocal()
    try:
        # Off by default, and an unknown flag id never claims to be on.
        assert settings_service.beta_enabled(db, user_id, "push_back_lessons") is False
        assert settings_service.beta_enabled(db, user_id, "time_travel") is False
    finally:
        db.close()

    toggled = client.put("/api/settings", json={"beta_features": {"push_back_lessons": True}})
    assert toggled.status_code == 200

    db = SessionLocal()
    try:
        assert settings_service.beta_enabled(db, user_id, "push_back_lessons") is True
        assert settings_service.beta_enabled(db, user_id, "time_travel") is False
    finally:
        db.close()
