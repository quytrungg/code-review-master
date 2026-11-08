"""`#N` cross-references between threads of one review.

Ordinals are 1-based positions in the review's thread list — the same numbers the workspace
shows in its `#1`, `#2` chips and the same ones the summariser references.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.review import MessageRole, ReviewThread, ThreadMessage

# Not preceded by a word character or an ampersand (avoids "&#39;" entities and "#abc1").
REFERENCE_RE = re.compile(r"(?<![\w&#])#(\d{1,3})\b")


@dataclass
class ThreadReference:
    ordinal: int
    file_path: str
    line_number: int
    finding: str
    conclusion: str


def _first_assistant(thread: ReviewThread) -> str:
    for message in thread.messages:
        if message.role == MessageRole.ASSISTANT:
            return message.content.strip()
    return ""


def _last_assistant(thread: ReviewThread) -> str:
    conclusion = ""
    for message in thread.messages:
        if message.role == MessageRole.ASSISTANT:
            conclusion = message.content.strip()
    return conclusion


def find_references(message: str, threads: list[ReviewThread]) -> list[ThreadReference]:
    """Resolve every `#N` in `message` that maps to an existing thread, in mention order."""
    seen: set[int] = set()
    found: list[ThreadReference] = []
    for match in REFERENCE_RE.finditer(message or ""):
        ordinal = int(match.group(1))
        if ordinal in seen or not (1 <= ordinal <= len(threads)):
            continue
        thread = threads[ordinal - 1]
        seen.add(ordinal)
        found.append(
            ThreadReference(
                ordinal=ordinal,
                file_path=thread.file_path,
                line_number=thread.line_number,
                finding=_first_assistant(thread),
                conclusion=_last_assistant(thread),
            )
        )
    return found


def format_references_block(references: list[ThreadReference]) -> str:
    if not references:
        return ""
    lines = [
        "## Referenced threads (the reviewer cited these by number)",
        "",
    ]
    for ref in references:
        lines.append(f"### #{ref.ordinal} — `{ref.file_path}:{ref.line_number}`")
        lines.append(f"Original finding: {ref.finding or '(none stored)'}")
        if ref.conclusion and ref.conclusion != ref.finding:
            lines.append(f"Latest conclusion: {ref.conclusion}")
        lines.append("")
    lines.append(
        "Treat these as the same review context: say whether the issues are the same, and keep "
        "your answer inside this thread."
    )
    return "\n".join(lines)


def first_message_text(messages: list[ThreadMessage]) -> str:
    for message in messages:
        if message.role == MessageRole.ASSISTANT:
            return message.content.strip()
    return ""
