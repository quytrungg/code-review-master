"""Local skill ingestion.

The skill folder is a library of markdown rule sets; it is far larger than a prompt budget.
The loader therefore always ships the entry file, then spends the remaining budget on the
reference files most relevant to the changed file set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import get_settings

SKILL_SUFFIXES = {".md", ".txt", ".yml"}
ENTRY_NAMES = ("SKILL.md", "skill.md", "README.md")
# Reference files that hold the review contract itself rather than one domain's rules.
CORE_TERMS = (
    "rubric",
    "verification",
    "output",
    "drafting",
    "google-style",
    "essential",
    "github-review-posting",
)
DEFAULT_MAX_CHARS = 80_000


@dataclass
class SkillBundle:
    text: str
    included: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def total_chars(self) -> int:
        return len(self.text)


def skill_root() -> Path:
    return get_settings().resolved_skills_dir


def skill_files(root: Path | None = None) -> list[Path]:
    """Every `.md`/`.txt` file under the skill directory, ordered for stable prompts."""
    base = root or skill_root()
    if not base.is_dir():
        return []
    return sorted(
        path
        for path in base.rglob("*")
        if path.is_file() and path.suffix.lower() in SKILL_SUFFIXES and not path.name.startswith(".")
    )


def manifest(root: Path | None = None) -> list[str]:
    base = root or skill_root()
    return [str(path.relative_to(base)) for path in skill_files(base)]


def _tokens(relative_path: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", relative_path.lower()) if len(token) > 2}


def _score(relative_path: str, hints: set[str]) -> int:
    tokens = _tokens(relative_path)
    score = 3 * len(tokens & hints)
    lower = relative_path.lower()
    score += sum(2 for term in CORE_TERMS if term in lower)
    if relative_path.count("/") == 0:
        score += 1
    return score


def _cap(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    cut = text.rfind("\n", 0, limit)
    return text[: cut if cut > 0 else limit] + "\n\n[… truncated to fit the prompt budget …]", True


def load_bundle(
    hints: set[str] | None = None, max_chars: int | None = None, root: Path | None = None
) -> SkillBundle:
    """Aggregate skill files into one prompt block within a character budget."""
    hints = hints or set()
    budget = max_chars if max_chars is not None else get_settings().skills_max_chars
    base = root or skill_root()
    files = skill_files(base)
    if not files:
        return SkillBundle(text="", included=[], skipped=[])

    entries = [f for f in files if f.name in ENTRY_NAMES and f.parent == base]
    ranked = sorted(
        (f for f in files if f not in entries),
        key=lambda f: (-_score(str(f.relative_to(base)), hints), str(f.relative_to(base))),
    )

    chunks: list[str] = []
    included: list[str] = []
    skipped: list[str] = []
    remaining = budget

    for path in entries + ranked:
        relative = str(path.relative_to(base))
        try:
            body = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            skipped.append(relative)
            continue
        if not body:
            skipped.append(relative)
            continue

        heading = f"## Skill file: {relative}\n\n"
        block = heading + body + "\n"
        if len(block) > remaining:
            if not included and remaining > 1000:
                # Always honour the entry file even if it alone exceeds the budget.
                capped, _ = _cap(block, remaining)
                chunks.append(capped)
                included.append(relative)
                remaining -= len(capped)
            else:
                skipped.append(relative)
            continue

        chunks.append(block)
        included.append(relative)
        remaining -= len(block)

    header = (
        "# Review standards\n\n"
        "The following rule sets were loaded from the repository's local skill library. "
        "They define the standard this review is held to.\n\n"
    )
    return SkillBundle(text=header + "\n".join(chunks), included=included, skipped=skipped)
