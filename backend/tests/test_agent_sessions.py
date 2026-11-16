"""Agent session mining: the three local stores, the window, and the analyze round trip."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import get_settings
from app.services import agent_sessions_service, llm_service
from tests.fixtures import as_result, create_llm_key

FOUNDATION = "code-review"


def _settings(monkeypatch, **paths: Path) -> None:
    """Point the service at fixture stores for one test."""
    settings = get_settings()
    for name, value in paths.items():
        monkeypatch.setattr(settings, name, str(value))


def _write_jsonl(path: Path, rows: list[dict], *, days_old: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    stamp = (datetime.now(timezone.utc) - timedelta(days=days_old)).timestamp()
    os.utime(path, (stamp, stamp))


def _iso(days_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _claude_root(tmp_path: Path, *, days_old: int = 0) -> Path:
    root = tmp_path / "claude" / "projects"
    _write_jsonl(
        root / "-repo-app" / "session-a.jsonl",
        [
            {
                "type": "assistant",
                "sessionId": "session-a",
                "cwd": "/repo/app",
                "timestamp": _iso(),
                "message": {"role": "assistant", "content": "Refactored the call site."},
            },
            {
                "type": "user",
                "sessionId": "session-a",
                "cwd": "/repo/app",
                "timestamp": _iso(),
                "message": {"role": "user", "content": "no, use the existing helper instead"},
            },
            {
                "type": "assistant",
                "sessionId": "session-a",
                "cwd": "/repo/app",
                "timestamp": _iso(),
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Rewrote the call site."}],
                },
            },
            {
                "type": "user",
                "sessionId": "session-a",
                "cwd": "/repo/app",
                "timestamp": _iso(),
                "message": {"role": "user", "content": "thanks, that works"},
            },
            {
                "type": "user",
                "sessionId": "session-a",
                "cwd": "/repo/app",
                "isSidechain": True,
                "timestamp": _iso(),
                "message": {"role": "user", "content": "no, that subagent branch is wrong"},
            },
            {
                "type": "assistant",
                "sessionId": "session-a",
                "cwd": "/repo/app",
                "timestamp": _iso(),
                "message": {"role": "assistant", "content": "Done."},
            },
        ],
        days_old=days_old,
    )
    return root


def _codex_root(tmp_path: Path, *, days_old: int = 0) -> Path:
    root = tmp_path / "codex" / "sessions"
    _write_jsonl(
        root / "2026" / "11" / "13" / "rollout-1.jsonl",
        [
            {
                "type": "session_meta",
                "timestamp": _iso(),
                "payload": {"id": "codex-1", "cwd": "/repo/codex"},
            },
            {
                "type": "response_item",
                "timestamp": _iso(),
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "The following is the Codex agent history whose contents you "
                            "must be aware of.",
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "timestamp": _iso(),
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Deleted the migration."}],
                },
            },
            {
                "type": "response_item",
                "timestamp": _iso(),
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "that's not what I asked"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": _iso(),
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Deleted the migration."}],
                },
            },
        ],
        days_old=days_old,
    )
    return root


def _hermes_db(tmp_path: Path, *, days_ago: int = 0) -> Path:
    db = tmp_path / "hermes" / "state.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db)
    try:
        connection.executescript(
            """
            CREATE TABLE sessions (id TEXT PRIMARY KEY, cwd TEXT, title TEXT);
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                timestamp REAL,
                active INTEGER DEFAULT 1,
                compacted INTEGER DEFAULT 0
            );
            """
        )
        stamp = (datetime.now(timezone.utc) - timedelta(days=days_ago)).timestamp()
        connection.execute(
            "INSERT INTO sessions (id, cwd, title) VALUES (?, ?, ?)",
            ("hermes-1", "/repo/hermes", "Fix the parser"),
        )
        connection.executemany(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            [
                ("hermes-1", "assistant", "Removed the guard clause.", stamp - 1),
                ("hermes-1", "user", "wrong again, revert that", stamp),
                ("hermes-1", "assistant", "Reverted the change.", stamp + 1),
            ],
        )
        connection.commit()
    finally:
        connection.close()
    return db


def _provision(client) -> None:
    create_llm_key(client, provider="ollama_local", default_model="llama3")
    key = client.get("/api/keys/llm").json()[0]
    client.put("/api/settings", json={"llm_key_id": key["id"]})


def _stub_model(monkeypatch, payload: dict) -> list[dict]:
    captured: list[dict] = []

    async def fake(credentials, model, system_prompt, user_prompt, **kwargs):
        captured.append({"user": user_prompt, "purpose": kwargs.get("purpose")})
        return json.dumps(payload)

    monkeypatch.setattr(llm_service, "generate", as_result(fake))
    return captured


# ------------------------------------------------------------------------------ sources


def test_available_sources_reports_missing_roots(tmp_path, monkeypatch):
    claude = tmp_path / "claude"
    claude.mkdir()
    hermes = _hermes_db(tmp_path)
    _settings(
        monkeypatch,
        claude_sessions_dir=claude,
        codex_sessions_dir=tmp_path / "missing-codex",
        hermes_state_db=hermes,
    )

    sources = {source.id: source for source in agent_sessions_service.available_sources()}

    assert sources["claude"].available is True
    assert sources["codex"].available is False
    assert sources["codex"].detail == "folder not found"
    assert sources["hermes"].available is True


# ------------------------------------------------------------------------------ readers


def test_claude_sessions_keep_the_correction_and_drop_the_chatter(tmp_path, monkeypatch):
    _settings(monkeypatch, claude_sessions_dir=_claude_root(tmp_path))

    digest = agent_sessions_service.summarise("claude", 30)

    assert digest.sessions == 1
    assert digest.exchanges == 1
    assert "use the existing helper instead" in digest.text
    assert "Rewrote the call site." in digest.text
    assert "thanks, that works" not in digest.text
    assert "subagent branch" not in digest.text


def test_codex_sessions_are_read_from_response_items(tmp_path, monkeypatch):
    _settings(monkeypatch, codex_sessions_dir=_codex_root(tmp_path))

    digest = agent_sessions_service.summarise("codex", 30)

    assert digest.sessions == 1
    assert digest.exchanges == 1
    assert "that's not what I asked" in digest.text
    assert "/repo/codex" in digest.text
    # The wrapper the CLI injects is not something the developer typed.
    assert "Codex agent history" not in digest.text


def test_injected_system_turns_are_not_treated_as_the_developer(tmp_path, monkeypatch):
    root = tmp_path / "claude" / "projects"
    _write_jsonl(
        root / "session-b.jsonl",
        [
            {
                "type": "assistant",
                "sessionId": "session-b",
                "cwd": "/repo/app",
                "timestamp": _iso(),
                "message": {"role": "assistant", "content": "Changed the guard clause."},
            },
            {
                "type": "user",
                "sessionId": "session-b",
                "cwd": "/repo/app",
                "timestamp": _iso(),
                "message": {
                    "role": "user",
                    "content": "<system-reminder>be careful</system-reminder> no, that's wrong",
                },
            },
            {
                "type": "assistant",
                "sessionId": "session-b",
                "cwd": "/repo/app",
                "timestamp": _iso(),
                "message": {"role": "assistant", "content": "Reverted it."},
            },
            {
                "type": "user",
                "sessionId": "session-b",
                "cwd": "/repo/app",
                "timestamp": _iso(),
                "message": {"role": "user", "content": "<command-name>/clear</command-name>"},
            },
            {
                "type": "assistant",
                "sessionId": "session-b",
                "cwd": "/repo/app",
                "timestamp": _iso(),
                "message": {"role": "assistant", "content": "Cleared."},
            },
            {
                "type": "user",
                "sessionId": "session-b",
                "cwd": "/repo/app",
                "timestamp": _iso(),
                "message": {
                    "role": "user",
                    "content": '<codex_internal_context source="goal">no, wrong</codex_internal_context>',
                },
            },
            {
                "type": "assistant",
                "sessionId": "session-b",
                "cwd": "/repo/app",
                "timestamp": _iso(),
                "message": {"role": "assistant", "content": "Done."},
            },
        ],
    )
    _settings(monkeypatch, claude_sessions_dir=root)

    digest = agent_sessions_service.summarise("claude", 30)

    assert digest.exchanges == 1
    assert "that's wrong" in digest.text
    assert "<system-reminder>" not in digest.text
    assert "codex_internal_context" not in digest.text
    assert "/clear" not in digest.text


def test_hermes_sessions_are_read_from_the_state_database(tmp_path, monkeypatch):
    _settings(monkeypatch, hermes_state_db=_hermes_db(tmp_path))

    digest = agent_sessions_service.summarise("hermes", 30)

    assert digest.sessions == 1
    assert digest.exchanges == 1
    assert "revert that" in digest.text
    assert "/repo/hermes" in digest.text


def test_sessions_outside_the_window_are_ignored(tmp_path, monkeypatch):
    _settings(
        monkeypatch,
        claude_sessions_dir=_claude_root(tmp_path, days_old=90),
        codex_sessions_dir=_codex_root(tmp_path, days_old=90),
        hermes_state_db=_hermes_db(tmp_path, days_ago=90),
    )

    for source in ("claude", "codex", "hermes"):
        digest = agent_sessions_service.summarise(source, 30)
        assert digest.sessions == 0
        assert digest.exchanges == 0


def test_malformed_lines_do_not_break_the_scan(tmp_path, monkeypatch):
    root = _claude_root(tmp_path)
    transcript = root / "-repo-app" / "session-a.jsonl"
    transcript.write_text(
        "{not json\n" + transcript.read_text(encoding="utf-8"), encoding="utf-8"
    )
    os.utime(transcript, None)
    _settings(monkeypatch, claude_sessions_dir=root)

    digest = agent_sessions_service.summarise("claude", 30)

    assert digest.exchanges == 1
    assert "use the existing helper instead" in digest.text


def test_a_missing_folder_is_a_warning_not_a_failure(tmp_path, monkeypatch):
    _settings(monkeypatch, codex_sessions_dir=tmp_path / "nowhere")

    digest = agent_sessions_service.summarise("codex", 30)

    assert digest.exchanges == 0
    assert any("was not found" in warning for warning in digest.warnings)


# --------------------------------------------------------------------------- the endpoint


def test_analysis_adds_the_chosen_sessions_to_the_prompt(client, tmp_path, monkeypatch):
    _provision(client)
    _settings(monkeypatch, claude_sessions_dir=_claude_root(tmp_path))
    captured = _stub_model(
        monkeypatch,
        {"analysisSummary": "Repeated rewrite requests.", "fileModifications": []},
    )

    response = client.post(
        f"/api/skills/{FOUNDATION}/analyze-history",
        json={"days": 30, "model": "ollama-local:llama3", "session_source": "claude"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["history"]["session_source"] == "claude"
    assert body["history"]["sessions"] == 1
    assert body["history"]["exchanges"] == 1
    prompt = captured[0]["user"]
    assert "# Agent coding sessions" in prompt
    assert "use the existing helper instead" in prompt
    assert captured[0]["purpose"] == "evolve"


def test_analysis_without_a_source_keeps_the_old_prompt(client, tmp_path, monkeypatch):
    _provision(client)
    _settings(monkeypatch, claude_sessions_dir=_claude_root(tmp_path))
    captured = _stub_model(
        monkeypatch,
        {"analysisSummary": "Nothing to change.", "fileModifications": []},
    )

    response = client.post(
        f"/api/skills/{FOUNDATION}/analyze-history",
        json={"days": 30, "model": "ollama-local:llama3"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["history"]["session_source"] is None
    assert body["history"]["sessions"] == 0
    assert "# Agent coding sessions" not in captured[0]["user"]


def test_a_missing_session_folder_still_analyses_the_reviews(client, tmp_path, monkeypatch):
    _provision(client)
    _settings(monkeypatch, codex_sessions_dir=tmp_path / "nowhere")
    _stub_model(
        monkeypatch,
        {"analysisSummary": "Only the review history applied.", "fileModifications": []},
    )

    response = client.post(
        f"/api/skills/{FOUNDATION}/analyze-history",
        json={"days": 30, "model": "ollama-local:llama3", "session_source": "codex"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["history"]["sessions"] == 0
    assert any("was not found" in warning for warning in body["warnings"])


def test_an_unknown_session_source_is_rejected(client):
    _provision(client)
    response = client.post(
        f"/api/skills/{FOUNDATION}/analyze-history",
        json={"days": 30, "model": "ollama-local:llama3", "session_source": "cursor"},
    )
    assert response.status_code == 422


def test_skills_listing_offers_the_three_sources(client, tmp_path, monkeypatch):
    _settings(
        monkeypatch,
        claude_sessions_dir=tmp_path / "claude",
        codex_sessions_dir=tmp_path / "codex",
        hermes_state_db=tmp_path / "hermes.db",
    )
    response = client.get("/api/skills")
    assert response.status_code == 200
    sources = {source["id"]: source for source in response.json()["session_sources"]}
    assert set(sources) == {"claude", "codex", "hermes"}
    assert all(source["available"] is False for source in sources.values())
