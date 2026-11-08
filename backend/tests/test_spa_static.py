from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture()
def spa_client(tmp_path, monkeypatch):
    """An app built with a fake `frontend/dist`, as the container image has."""
    (tmp_path / "index.html").write_text("<!doctype html><title>spa</title>", encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('spa');", encoding="utf-8")

    monkeypatch.setenv("FRONTEND_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        yield TestClient(create_app())
    finally:
        get_settings.cache_clear()


def test_index_and_client_routes_serve_the_built_frontend(spa_client):
    index = spa_client.get("/")
    assert index.status_code == 200
    assert "text/html" in index.headers["content-type"]
    assert "<title>spa</title>" in index.text

    # React Router owns this path; a refresh must not 404.
    deep_link = spa_client.get("/reviews/12")
    assert deep_link.status_code == 200
    assert "<title>spa</title>" in deep_link.text


def test_assets_are_served_and_missing_assets_still_404(spa_client):
    asset = spa_client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "console.log('spa');" in asset.text

    missing = spa_client.get("/assets/does-not-exist.js")
    assert missing.status_code == 404


def test_api_routes_win_over_the_static_mount(spa_client):
    health = spa_client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


def test_no_mount_without_frontend_dir(monkeypatch):
    """A development checkout has no FRONTEND_DIR, so `/` stays the API's 404."""
    monkeypatch.delenv("FRONTEND_DIR", raising=False)
    get_settings.cache_clear()
    try:
        assert TestClient(create_app()).get("/").status_code == 404
    finally:
        get_settings.cache_clear()
