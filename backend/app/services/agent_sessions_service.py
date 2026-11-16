"""Mine the local CLI-agent sessions as evidence for skill evolution.

The review history only records friction that reached a pull request. The same friction usually
happens earlier and much more often in the developer's own Claude Code, Codex or Hermes sessions:
"no, use the existing helper", "that test was already passing", "don't touch staging config". Those
corrections are free evidence about the rules the assistant should follow, and they never leave the
machine unless the operator explicitly runs an analysis.

This module reads the last N days of the chosen tool's own store — read-only, never writing to it —
condenses the user turns that push back on the assistant into one line per exchange, and hands the
result to `skill_analyzer_service` as an extra prompt section.

Three readers, one shape:

- **Claude Code** — `~/.claude/projects/**/*.jsonl`, one JSON object per line, `type` is
  `user`/`assistant` and the text lives in `message.content` (a string or a list of blocks).
- **Codex** — `~/.codex/sessions/**/*.jsonl`, one JSON object per line, `response_item` rows carry
  `payload.type == "message"` with `input_text`/`output_text` content blocks.
- **Hermes** — `~/.hermes/state.db` (SQLite) with `sessions` and `messages` tables; opened
  `mode=ro` so a live agent process keeps its own write locks.

Every reader is fault-tolerant: a malformed line is skipped, and a vanished file, a missing folder
or a missing table becomes one warning, because the review half of the analysis is still worth
running.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from app.core.config import get_settings
from app.db.base import utcnow

logger = logging.getLogger(__name__)

SessionSourceId = Literal["claude", "codex", "hermes"]

SOURCE_LABELS: dict[str, str] = {
    "claude": "Claude Code",
    "codex": "Codex",
    "hermes": "Hermes",
}


def label_for(source: str) -> str:
    return SOURCE_LABELS.get(source, source.title())


# How much of one turn survives into the digest. The assistant's turn is context, not evidence, so
# it is shortened further than the user's correction.
USER_EXCERPT_CHARS = 240
ASSISTANT_EXCERPT_CHARS = 180
# How many correction exchanges one session may contribute, so a single long session cannot crowd
# out every other session in the window.
MAX_EXCHANGES_PER_SESSION = 8
# Cap on distinct markers counted for one correction, so a rant does not outrank precision.
MAX_SCORE = 5

_MARKERS = (
    re.compile(r"\bno\b", re.IGNORECASE),
    re.compile(r"\bnope\b", re.IGNORECASE),
    re.compile(r"\bwrong\b", re.IGNORECASE),
    re.compile(r"\bincorrect\b", re.IGNORECASE),
    re.compile(r"\bactually\b", re.IGNORECASE),
    re.compile(r"\binstead\b", re.IGNORECASE),
    re.compile(r"\bdon'?t\b", re.IGNORECASE),
    re.compile(r"\bstop\b", re.IGNORECASE),
    re.compile(r"\brevert\b", re.IGNORECASE),
    re.compile(r"\bundo\b", re.IGNORECASE),
    re.compile(r"\bbroken\b", re.IGNORECASE),
    re.compile(r"\bfailed\b", re.IGNORECASE),
    re.compile(r"\bagain\b", re.IGNORECASE),
    re.compile(r"\bstill\b", re.IGNORECASE),
    re.compile(r"\bnot what\b", re.IGNORECASE),
    re.compile(r"\bi said\b", re.IGNORECASE),
    re.compile(r"\bi asked\b", re.IGNORECASE),
    re.compile(r"\byou missed\b", re.IGNORECASE),
    re.compile(r"\byou forgot\b", re.IGNORECASE),
    re.compile(r"\bthat'?s not\b", re.IGNORECASE),
    re.compile(r"\bwhy did you\b", re.IGNORECASE),
    re.compile(r"\bshouldn'?t\b", re.IGNORECASE),
    re.compile(r"\bdidn'?t\b", re.IGNORECASE),
)

# Tool-injected user turns. A CLI agent writes its environment, its skills and its own history
# into the transcript as "user" messages; treating those as the developer talking would fill the
# digest with instructions the developer never wrote.
_SYSTEM_BLOCK = re.compile(r"<system-reminder>.*?</system-reminder>", re.IGNORECASE | re.DOTALL)
_SYNTHETIC_TAG = re.compile(r"^<([a-z_]+)[\s>]", re.IGNORECASE)
_SYNTHETIC_TAG_WORDS = (
    "context",
    "instruction",
    "reminder",
    "skill",
    "command",
    "system",
    "internal",
    "subagent",
    "goal",
)
_SYNTHETIC_PREFIXES = (
    "<local-command",
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<environment_context>",
    "<user_instructions>",
    "<subagent_notification>",
    "<skill>",
    "<turn_aborted>",
    "another claude session sent a message:",
    "act as the ",
    "act as a ",
    "you are a ",
    "you are an ",
    "you are the ",
    "# agents.md instructions",
    "base directory for this skill:",
    "the following is the codex agent history",
)


def _human_text(text: str) -> str:
    """Drop injected system blocks and synthetic turns; keep what the developer typed."""
    cleaned = _SYSTEM_BLOCK.sub("", text).strip()
    if not cleaned:
        return ""
    tag = _SYNTHETIC_TAG.match(cleaned)
    if tag and any(word in tag.group(1).lower() for word in _SYNTHETIC_TAG_WORDS):
        return ""
    lowered = cleaned.lower()
    if any(lowered.startswith(prefix) for prefix in _SYNTHETIC_PREFIXES):
        return ""
    return cleaned


@dataclass
class SessionSourceInfo:
    """One selectable source, as the Skills page needs it."""

    id: SessionSourceId
    label: str
    path: str
    available: bool
    detail: str | None = None


@dataclass
class SessionExchange:
    """One user turn that corrected the assistant, with the turn it corrected."""

    source: str
    session_id: str
    project: str
    timestamp: datetime | None
    score: int
    user_text: str
    assistant_text: str = ""

    def render(self) -> str:
        when = self.timestamp.date().isoformat() if self.timestamp else "unknown date"
        place = self.project or "unknown project"
        parts = [
            f"[{self.source} · {when} · {place}]",
            f"User: {self.user_text}",
        ]
        if self.assistant_text:
            parts.append(f"Agent: {self.assistant_text}")
        return " -> ".join(parts)


@dataclass
class SessionDigest:
    """The condensed agent-session evidence behind one analysis."""

    source: SessionSourceId
    days: int
    sessions: int = 0
    exchanges: int = 0
    text: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Turn:
    """One readable user/assistant turn, before pairing and scoring."""

    source: str
    session_id: str
    role: Literal["user", "assistant"]
    text: str
    timestamp: datetime | None = None
    project: str = ""


# --------------------------------------------------------------------------- sources


def _display(path: Path) -> str:
    """`/Users/me/.claude/projects` → `~/.claude/projects` for the browser and the prompt."""
    try:
        home = Path.home()
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


def available_sources() -> list[SessionSourceInfo]:
    """Every source this machine can offer, whether or not its folder exists."""
    settings = get_settings()
    claude = settings.resolved_claude_sessions_dir
    codex = settings.resolved_codex_sessions_dir
    hermes = settings.resolved_hermes_state_db
    return [
        SessionSourceInfo(
            id="claude",
            label="Claude Code",
            path=_display(claude),
            available=claude.is_dir(),
            detail=None if claude.is_dir() else "folder not found",
        ),
        SessionSourceInfo(
            id="codex",
            label="Codex",
            path=_display(codex),
            available=codex.is_dir(),
            detail=None if codex.is_dir() else "folder not found",
        ),
        SessionSourceInfo(
            id="hermes",
            label="Hermes",
            path=_display(hermes),
            available=hermes.is_file(),
            detail=None if hermes.is_file() else "state.db not found",
        ),
    ]


# --------------------------------------------------------------------------- reading


def _excerpt(text: str | None, limit: int) -> str:
    body = " ".join((text or "").split())
    if len(body) > limit:
        body = body[:limit].rstrip() + "…"
    return body


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iter_jsonl(path: Path, byte_budget: int) -> Iterator[dict]:
    """Parse one JSONL file, skipping malformed lines and stopping at the byte budget."""
    read = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                read += len(line)
                if read > byte_budget:
                    break
                body = line.strip()
                if not body:
                    continue
                try:
                    parsed = json.loads(body)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    yield parsed
    except OSError:
        # A path is not PII, but it does carry a username; the count is enough to debug a scan.
        logger.warning("Could not read an agent session transcript")
        return


def _jsonl_files(root: Path, since: datetime, limit: int) -> list[Path]:
    """The newest transcript files inside the window, capped before any parsing happens."""
    cutoff = since.timestamp()
    files: list[tuple[float, Path]] = []
    for path in root.rglob("*.jsonl"):
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime < cutoff:
            continue
        files.append((stat.st_mtime, path))
    files.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in files[:limit]]


def _content_text(content: object) -> str:
    """Text out of a string or a list of content blocks, ignoring tool calls and images."""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") not in ("text", "input_text", "output_text"):
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts)


def _claude_turns(root: Path, since: datetime) -> tuple[list[_Turn], list[str]]:
    settings = get_settings()
    turns: list[_Turn] = []
    unreadable = 0
    for path in _jsonl_files(root, since, settings.agent_session_max_files):
        project = ""
        session_id = path.stem
        for obj in _iter_jsonl(path, settings.agent_session_file_max_bytes):
            kind = obj.get("type")
            if kind == "summary" or kind not in ("user", "assistant"):
                continue
            if obj.get("isSidechain"):
                # A subagent conversation interleaved with the main one; pairing its turns with the
                # parent's assistant turns would invent a correction that never happened.
                continue
            project = obj.get("cwd") or project
            session_id = obj.get("sessionId") or session_id
            message = obj.get("message")
            role = message.get("role") if isinstance(message, dict) else kind
            if role not in ("user", "assistant"):
                role = kind
            text = _content_text(message.get("content") if isinstance(message, dict) else "")
            if role == "user":
                text = _human_text(text)
            if not text:
                unreadable += 1
                continue
            turns.append(
                _Turn(
                    source="claude",
                    session_id=str(session_id),
                    role=role,
                    text=text,
                    timestamp=_parse_timestamp(obj.get("timestamp")),
                    project=project,
                )
            )
    if unreadable:
        logger.debug("Skipped %s claude turn(s) without text", unreadable)
    return turns, []


def _codex_turns(root: Path, since: datetime) -> tuple[list[_Turn], list[str]]:
    settings = get_settings()
    turns: list[_Turn] = []
    for path in _jsonl_files(root, since, settings.agent_session_max_files):
        project = ""
        session_id = path.stem
        for obj in _iter_jsonl(path, settings.agent_session_file_max_bytes):
            payload = obj.get("payload")
            if not isinstance(payload, dict):
                continue
            timestamp = _parse_timestamp(obj.get("timestamp"))
            if obj.get("type") == "session_meta":
                project = payload.get("cwd") or project
                session_id = payload.get("id") or session_id
                continue
            if obj.get("type") != "response_item" or payload.get("type") != "message":
                continue
            role = payload.get("role")
            if role not in ("user", "assistant"):
                continue
            text = _content_text(payload.get("content"))
            if role == "user":
                text = _human_text(text)
            if not text:
                continue
            turns.append(
                _Turn(
                    source="codex",
                    session_id=str(session_id),
                    role=role,
                    text=text,
                    timestamp=timestamp,
                    project=project,
                )
            )
    return turns, []


def _hermes_turns(state_db: Path, since: datetime) -> tuple[list[_Turn], list[str]]:
    settings = get_settings()
    turns: list[_Turn] = []
    try:
        connection = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as exc:
        return [], [f"Could not open the Hermes session database: {exc}"]
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT m.session_id, m.role, m.content, m.timestamp, s.cwd, s.title
            FROM messages AS m
            JOIN sessions AS s ON s.id = m.session_id
            WHERE m.role IN ('user', 'assistant')
              AND COALESCE(m.active, 1) = 1
              AND COALESCE(m.compacted, 0) = 0
              AND m.timestamp >= ?
            ORDER BY m.timestamp DESC
            LIMIT ?
            """,
            (since.timestamp(), settings.agent_session_max_messages),
        )
        for row in rows:
            timestamp = _parse_timestamp(row["timestamp"])
            role = row["role"]
            if role not in ("user", "assistant"):
                continue
            text = _content_text(row["content"])
            if role == "user":
                text = _human_text(text)
            if not text:
                continue
            turns.append(
                _Turn(
                    source="hermes",
                    session_id=str(row["session_id"]),
                    role=role,
                    text=text,
                    timestamp=timestamp,
                    project=(row["cwd"] or row["title"] or ""),
                )
            )
    except sqlite3.Error as exc:
        return [], [f"Could not read the Hermes session database: {exc}"]
    finally:
        connection.close()
    return turns, []


# --------------------------------------------------------------------------- condensing


def _score(text: str) -> int:
    return min(MAX_SCORE, sum(1 for marker in _MARKERS if marker.search(text)))


def _exchanges(turns: Iterable[_Turn]) -> list[SessionExchange]:
    """Pair a user turn with the assistant turn it corrects and score the correction.

    A session's first user turn is the task the developer handed over, not a correction, so it is
    skipped: an exchange only counts once the assistant has already spoken in that session. That
    also drops the role prompts a CLI agent writes into its own transcript.
    """
    sessions: dict[tuple[str, str], list[_Turn]] = {}
    for turn in turns:
        sessions.setdefault((turn.source, turn.session_id), []).append(turn)

    exchanges: list[SessionExchange] = []
    for (source, session_id), items in sessions.items():
        items.sort(key=lambda item: item.timestamp or datetime.min.replace(tzinfo=timezone.utc))
        session_exchanges: list[SessionExchange] = []
        pending: _Turn | None = None
        assistant_seen = False
        for turn in items:
            if turn.role == "assistant":
                assistant_seen = True
                if pending is not None:
                    score = _score(pending.text)
                    if score > 0:
                        session_exchanges.append(
                            SessionExchange(
                                source=source,
                                session_id=session_id,
                                project=pending.project,
                                timestamp=pending.timestamp,
                                score=score,
                                user_text=_excerpt(pending.text, USER_EXCERPT_CHARS),
                                assistant_text=_excerpt(turn.text, ASSISTANT_EXCERPT_CHARS),
                            )
                        )
                    pending = None
                continue
            pending = turn if assistant_seen else None
        session_exchanges.sort(
            key=lambda item: (
                -item.score,
                item.timestamp or datetime.min.replace(tzinfo=timezone.utc),
            )
        )
        exchanges.extend(session_exchanges[:MAX_EXCHANGES_PER_SESSION])
    return exchanges


def summarise(source: SessionSourceId, days: int) -> SessionDigest:
    """Read the chosen tool's store and condense the last `days` of corrections.

    A missing folder is a warning, not an error: the analysis still has the review history, and the
    operator can pick another source next time.
    """
    days = max(1, days)
    since = utcnow() - timedelta(days=days)
    settings = get_settings()
    digest = SessionDigest(source=source, days=days)

    if source == "claude":
        root = settings.resolved_claude_sessions_dir
        if not root.is_dir():
            digest.warnings.append(f"The Claude Code folder {_display(root)} was not found.")
            digest.text = "(no agent sessions were readable)"
            return digest
        turns, warnings = _claude_turns(root, since)
    elif source == "codex":
        root = settings.resolved_codex_sessions_dir
        if not root.is_dir():
            digest.warnings.append(f"The Codex folder {_display(root)} was not found.")
            digest.text = "(no agent sessions were readable)"
            return digest
        turns, warnings = _codex_turns(root, since)
    else:
        state_db = settings.resolved_hermes_state_db
        if not state_db.is_file():
            digest.warnings.append(f"The Hermes database {_display(state_db)} was not found.")
            digest.text = "(no agent sessions were readable)"
            return digest
        turns, warnings = _hermes_turns(state_db, since)

    digest.warnings.extend(warnings)
    digest.sessions = len({(turn.source, turn.session_id) for turn in turns})
    if not turns:
        digest.text = "(no agent sessions in this window were readable)"
        return digest

    exchanges = _exchanges(turns)
    exchanges.sort(
        key=lambda item: (
            -item.score,
            -(item.timestamp.timestamp() if item.timestamp else 0.0),
            item.session_id,
        )
    )
    lines: list[str] = []
    used = 0
    for exchange in exchanges:
        line = exchange.render()
        if used + len(line) + 1 > settings.agent_session_max_chars:
            break
        lines.append(line)
        used += len(line) + 1
    digest.exchanges = len(lines)
    if lines:
        digest.text = "\n".join(lines)
    elif exchanges:
        digest.text = "(the corrections in this window were too long to include)"
    else:
        digest.text = "(the developer did not push back on the agent in this window)"
    return digest
