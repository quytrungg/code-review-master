from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.core.config import get_settings


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def _skills_dir() -> Path:
    return get_settings().resolved_skills_dir


def _foundations_dir() -> Path:
    return get_settings().resolved_foundations_dir


def test_default_foundation_is_listed_with_its_files(client):
    body = client.get("/api/skills").json()
    assert body["default"] == "code-review"
    default = next(f for f in body["foundations"] if f["id"] == "code-review")
    assert default["is_default"] is True
    assert "SKILL.md" in default["files"]
    assert default["file_count"] == len(default["files"]) == 2
    assert default["total_chars"] > 0


def test_single_file_upload_lands_in_the_default_foundation(client):
    response = client.post(
        "/api/skills/files",
        files={"file": ("My Rules.md", b"# My rules\n\nDo the thing.", "text/markdown")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["path"] == "my-rules.md"
    assert body["foundation"] == "code-review"
    assert (_skills_dir() / "my-rules.md").read_text() == "# My rules\n\nDo the thing."

    listing = client.get("/api/skills").json()
    default = next(f for f in listing["foundations"] if f["id"] == "code-review")
    assert "my-rules.md" in default["files"]


def test_single_file_upload_does_not_overwrite(client):
    first = client.post("/api/skills/files", files={"file": ("rules.md", b"one", "text/markdown")})
    second = client.post("/api/skills/files", files={"file": ("rules.md", b"two", "text/markdown")})
    assert first.json()["path"] == "rules.md"
    assert second.json()["path"] == "rules-2.md"
    assert (_skills_dir() / "rules.md").read_text() == "one"
    assert (_skills_dir() / "rules-2.md").read_text() == "two"


def test_unsupported_extension_is_rejected(client):
    response = client.post(
        "/api/skills/files", files={"file": ("rules.json", b"{}", "application/json")}
    )
    assert response.status_code == 422
    assert ".md and .txt" in response.json()["detail"]


def test_empty_file_is_rejected(client):
    response = client.post("/api/skills/files", files={"file": ("empty.md", b"", "text/markdown")})
    assert response.status_code == 422


def test_folder_upload_strips_the_wrapper_directory(client):
    response = client.post(
        "/api/skills/foundations",
        data={"name": "frontend-guidelines"},
        files=[
            ("files", ("frontend-guidelines/react.md", b"# React\n\nHooks.", "text/markdown")),
            ("files", ("frontend-guidelines/a11y.txt", b"A11y rules", "text/plain")),
        ],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == "frontend-guidelines"
    assert sorted(body["files"]) == ["a11y.txt", "react.md"]
    assert body["is_default"] is False
    assert (_foundations_dir() / "frontend-guidelines" / "react.md").is_file()


def test_zip_upload_extracts_and_skips_noise(client):
    payload = _zip(
        {
            "guidelines/": b"",
            "guidelines/security.md": b"# Security\n\nValidate input.",
            "guidelines/__MACOSX/._security.md": b"junk",
            "guidelines/.DS_Store": b"junk",
            "guidelines/logo.png": b"\x89PNG",
        }
    )
    response = client.post(
        "/api/skills/foundations",
        data={"name": "security-pack"},
        files={"archive": ("pack.zip", payload, "application/zip")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["files"] == ["security.md"]


def test_zip_traversal_is_not_written_outside_the_foundation(client):
    payload = _zip({"../../evil.md": b"pwned", "ok.md": b"fine"})
    response = client.post(
        "/api/skills/foundations",
        data={"name": "tricky"},
        files={"archive": ("tricky.zip", payload, "application/zip")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["files"] == ["ok.md"]
    assert not (_foundations_dir().parent / "evil.md").exists()
    assert not (Path("/tmp") / "evil.md").exists()


def test_duplicate_foundation_id_is_a_conflict(client):
    files = [("files", ("a.md", b"# A", "text/markdown"))]
    first = client.post("/api/skills/foundations", data={"name": "dup"}, files=files)
    assert first.status_code == 201
    second = client.post("/api/skills/foundations", data={"name": "dup"}, files=files)
    assert second.status_code == 409


def test_reserved_and_invalid_names_are_rejected(client):
    files = [("files", ("a.md", b"# A", "text/markdown"))]
    reserved = client.post("/api/skills/foundations", data={"name": "code-review"}, files=files)
    assert reserved.status_code == 409
    invalid = client.post("/api/skills/foundations", data={"name": "Not A Slug!"}, files=files)
    assert invalid.status_code == 422


def test_foundation_without_markdown_is_rejected(client):
    response = client.post(
        "/api/skills/foundations",
        data={"name": "empty-pack"},
        files=[("files", ("readme.rst", b"nope", "text/plain"))],
    )
    assert response.status_code == 422
    assert "No .md or .txt" in response.json()["detail"]
    assert not (_foundations_dir() / "empty-pack").exists()


def test_file_cap_is_enforced(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "foundation_max_files", 2)
    response = client.post(
        "/api/skills/foundations",
        data={"name": "too-many"},
        files=[("files", (f"f{i}.md", b"x", "text/markdown")) for i in range(3)],
    )
    assert response.status_code == 413


def test_delete_removes_an_uploaded_foundation_only(client):
    client.post(
        "/api/skills/foundations",
        data={"name": "throwaway"},
        files=[("files", ("a.md", b"# A", "text/markdown"))],
    )
    assert client.delete("/api/skills/foundations/throwaway").status_code == 204
    assert not (_foundations_dir() / "throwaway").exists()

    default = client.delete("/api/skills/foundations/code-review")
    assert default.status_code == 400
    assert "built-in" in default.json()["detail"]

    assert client.delete("/api/skills/foundations/ghost").status_code == 404


@pytest.mark.parametrize("bad", ["../escape", "/etc", "name with spaces"])
def test_delete_rejects_paths_outside_the_root(client, bad):
    assert client.delete(f"/api/skills/foundations/{bad}").status_code in (404, 405)
