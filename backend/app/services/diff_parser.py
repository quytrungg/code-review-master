"""Unified-diff parsing and line anchoring.

GitHub's review API only accepts an inline comment on a line that exists on the chosen
side of the diff, so every finding the model returns has to be mapped back onto a real
RIGHT-side line before it is stored or posted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")

# Files that add noise without review value, or that are generated.
SKIP_EXACT = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bun.lockb",
    "Gemfile.lock",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "go.sum",
    "composer.lock",
    ".DS_Store",
}
SKIP_SUFFIXES = (
    ".min.js",
    ".min.css",
    ".map",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".mp4",
    ".mov",
    ".snap",
)
SKIP_SEGMENTS = {"node_modules", "vendor/bundle", "dist", "build", ".venv", "__pycache__"}

ADD = "add"
DEL = "del"
CONTEXT = "context"
META = "meta"


@dataclass
class Line:
    kind: str
    old_no: int | None
    new_no: int | None
    text: str

    @property
    def sign(self) -> str:
        return {ADD: "+", DEL: "-", CONTEXT: " "}.get(self.kind, "")


@dataclass
class Hunk:
    header: str
    section: str
    lines: list[Line] = field(default_factory=list)

    def render_numbered(self) -> str:
        """This hunk with the RIGHT-side line number in the left column.

        Deleted lines have no new-file number, so their column is blank — this keeps every number
        the model can see a legal anchor for a comment on the new file. Rendered per hunk so a
        prompt budget can drop whole hunks instead of cutting one in half.
        """
        out: list[str] = [self.header]
        for line in self.lines:
            if line.kind == META:
                out.append(line.text)
                continue
            number = f"{line.new_no:>6}" if line.new_no is not None else " " * 6
            out.append(f"{number} {line.sign} {line.text}")
        return "\n".join(out)


@dataclass
class FileDiff:
    path: str
    old_path: str | None = None
    hunks: list[Hunk] = field(default_factory=list)
    is_binary: bool = False
    is_new: bool = False
    is_deleted: bool = False
    skipped_reason: str | None = None

    @property
    def added(self) -> int:
        return sum(1 for h in self.hunks for line in h.lines if line.kind == ADD)

    @property
    def removed(self) -> int:
        return sum(1 for h in self.hunks for line in h.lines if line.kind == DEL)

    def right_lines(self) -> dict[int, Line]:
        """Right-side (new file) line numbers mapped to their line."""
        return {line.new_no: line for h in self.hunks for line in h.lines if line.new_no is not None}

    def render_numbered(self) -> str:
        """Every hunk, numbered. See `Hunk.render_numbered`."""
        return "\n".join(hunk.render_numbered() for hunk in self.hunks)


def _unquote_path(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    return raw.replace("\\t", "\t").replace('\\"', '"')


def _clean_path(raw: str) -> str:
    path = _unquote_path(raw)
    if path.startswith(("a/", "b/")):
        path = path[2:]
    if path.startswith("./"):
        path = path[2:]
    return path


def should_skip(path: str) -> str | None:
    """Return a human-readable reason when a changed file is not worth reviewing."""
    name = path.rsplit("/", 1)[-1]
    if name in SKIP_EXACT:
        return "lockfile or generated manifest"
    if name.lower().endswith(SKIP_SUFFIXES):
        return "binary or generated asset"
    for segment in SKIP_SEGMENTS:
        if f"/{segment}/" in path or path.startswith(f"{segment}/"):
            return f"vendored/generated directory ({segment})"
    return None


def parse_diff(diff_text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    current: FileDiff | None = None
    current_hunk: Hunk | None = None
    old_no = new_no = 0

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            match = re.match(r"^diff --git (a/.+?) (b/.+)$", raw)
            path = _clean_path(match.group(2)) if match else raw[len("diff --git ") :]
            current = FileDiff(path=path)
            files.append(current)
            current_hunk = None
            continue

        if current is None:
            continue

        if raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
            current.is_binary = True
            current.skipped_reason = current.skipped_reason or "binary file"
            continue

        if raw.startswith("new file mode"):
            current.is_new = True
            continue
        if raw.startswith("deleted file mode"):
            current.is_deleted = True
            continue

        if raw.startswith("--- "):
            target = raw[4:].split("\t")[0]
            if target.strip() == "/dev/null":
                current.is_new = True
            else:
                current.old_path = _clean_path(target)
            continue

        if raw.startswith("+++ "):
            target = raw[4:].split("\t")[0]
            if target.strip() == "/dev/null":
                current.is_deleted = True
            else:
                current.path = _clean_path(target)
            continue

        hunk_match = HUNK_RE.match(raw)
        if hunk_match:
            old_no = int(hunk_match.group(1))
            new_no = int(hunk_match.group(3))
            current_hunk = Hunk(header=raw, section=(hunk_match.group(5) or "").strip())
            current.hunks.append(current_hunk)
            continue

        if current_hunk is None:
            continue

        if raw.startswith("\\"):
            current_hunk.lines.append(Line(META, None, None, raw))
            continue

        prefix, text = (raw[0], raw[1:]) if raw else (" ", "")
        if prefix == "+":
            current_hunk.lines.append(Line(ADD, None, new_no, text))
            new_no += 1
        elif prefix == "-":
            current_hunk.lines.append(Line(DEL, old_no, None, text))
            old_no += 1
        else:
            current_hunk.lines.append(Line(CONTEXT, old_no, new_no, text))
            old_no += 1
            new_no += 1

    for item in files:
        if item.skipped_reason is None:
            item.skipped_reason = should_skip(item.path)
    return files


def reviewable_files(files: list[FileDiff]) -> list[FileDiff]:
    return [
        f
        for f in files
        if f.skipped_reason is None and f.hunks and not f.is_binary and f.right_lines()
    ]


def resolve_path(files: list[FileDiff], reported: str) -> FileDiff | None:
    """Match a model-reported path against the parsed files.

    Accepts exact matches, then a single unique basename match, tolerating `a/`/`b/` and
    `./` prefixes the model may echo from the diff header.
    """
    target = _clean_path(reported or "")
    if not target:
        return None
    for item in files:
        if item.path == target:
            return item
    basename = target.rsplit("/", 1)[-1]
    candidates = [f for f in files if f.path.rsplit("/", 1)[-1] == basename]
    return candidates[0] if len(candidates) == 1 else None


def anchor_line(file_diff: FileDiff, line_number: int) -> int | None:
    """Closest legal RIGHT-side line, preferring the requested one, then the nearest below."""
    right = file_diff.right_lines()
    if not right:
        return None
    if line_number in right:
        return line_number
    ordered = sorted(right)
    below = [n for n in ordered if n >= line_number]
    if below:
        return below[0]
    return ordered[-1]


def rebuild_snippet(file_diff: FileDiff, line_number: int, context: int = 2) -> str:
    """Reconstruct `@@ header` plus a small numbered window around the anchor.

    Used both as the code box in the UI and as GitHub's `diff_hunk`-style context.
    """
    for hunk in file_diff.hunks:
        indices = [i for i, line in enumerate(hunk.lines) if line.new_no == line_number]
        if not indices:
            continue
        center = indices[0]
        start = max(0, center - context)
        end = min(len(hunk.lines), center + context + 1)
        body = "\n".join(line.sign + line.text for line in hunk.lines[start:end] if line.kind != META)
        return f"{hunk.header}\n{body}"
    return file_diff.hunks[0].header if file_diff.hunks else ""


def snippet_contains_line(snippet: str, line_text: str) -> bool:
    needle = (line_text or "").strip()
    if not needle:
        return False
    return any(needle in row.strip() for row in snippet.splitlines())


def language_hints(files) -> set[str]:
    """Tokens from changed paths used to rank skill reference files.

    Accepts `FileDiff` objects or plain path strings (discussion turns only have paths).
    """
    mapping = {
        ".rb": {"ruby", "rails", "backend"},
        ".rake": {"ruby", "rails"},
        ".erb": {"ruby", "rails", "frontend"},
        ".ts": {"typescript", "frontend"},
        ".tsx": {"typescript", "react", "frontend"},
        ".js": {"javascript", "frontend"},
        ".jsx": {"javascript", "react", "frontend"},
        ".css": {"css", "frontend"},
        ".scss": {"css", "frontend"},
        ".py": {"python", "backend"},
        ".go": {"go", "backend"},
        ".sql": {"sql", "data", "migrations"},
        ".yml": {"ci", "config"},
        ".yaml": {"ci", "config"},
    }
    hints: set[str] = set()
    for item in files:
        path = (item.path if hasattr(item, "path") else str(item)).lower()
        suffix = "." + path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
        hints |= mapping.get(suffix, set())
        lowered = path.replace("_", "/").replace("-", "/")
        hints |= {part for part in lowered.split("/") if len(part) > 3}
        for token in ("report", "leave", "payroll", "mobile", "security", "job", "migration", "test"):
            if token in path:
                hints.add(token)
    return hints
