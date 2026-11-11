"""Core Skill Foundations: discovery, upload, extraction and deletion.

The filesystem is the single source of truth — there is no table of foundations, so a folder
added or removed by hand is reflected immediately. Two roots participate:

* the configured skills directory (default `code-review/`) — the protected default foundation
* `FOUNDATIONS_DIR` (default `code-review-foundations/`) — one sub-folder per uploaded foundation
"""

from __future__ import annotations

import io
import os
import re
import shutil
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings

DEFAULT_FOUNDATION = "code-review"
# `.yml` is writable so a foundation can carry machine-readable rules; the loader reads it too.
ALLOWED_SUFFIXES = {".md", ".txt", ".yml"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,49}$")
# A clone name is stricter than a foundation id: kebab-case only (phase 34).
CLONE_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SKIP_DIRS = {"__MACOSX", "__pycache__", ".git"}
SKIP_NAMES = {".DS_Store", "Thumbs.db"}


class SkillError(Exception):
    """Operator-facing failure with an HTTP status."""

    def __init__(self, detail: str, status_code: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


READ_ONLY_DETAIL = (
    "Skill files are read-only on this deployment. Add markdown to code-review/ in the repository "
    "and redeploy; runtime uploads return with object storage (phase 21)."
)


def require_writable() -> None:
    """Serverless deployments have no writable skill directory; refuse instead of writing /tmp."""
    if get_settings().serverless:
        raise SkillError(READ_ONLY_DETAIL, 403)


@dataclass
class FoundationInfo:
    id: str
    label: str
    path: Path
    is_default: bool
    files: list[str] = field(default_factory=list)
    total_chars: int = 0

    @property
    def file_count(self) -> int:
        return len(self.files)


def _root() -> Path:
    return get_settings().resolved_foundations_dir


def _default_root() -> Path:
    return get_settings().resolved_skills_dir


def slugify_filename(name: str) -> str:
    """`My Rules.md` → `my-rules.md`, keeping a known suffix."""
    path = Path(name.replace("\\", "/").strip())
    stem = path.stem.lower()
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise SkillError(
            f"Only .md, .txt and .yml files are supported (got '{name}')."
        )
    slug = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    if not slug:
        raise SkillError(f"'{name}' has no usable filename.")
    return f"{slug[:80]}{suffix}"


def validate_slug(name: str) -> str:
    slug = (name or "").strip().lower()
    if not SLUG_RE.match(slug):
        raise SkillError(
            "Foundation name must be 1-50 characters: lowercase letters, digits, '-' or '_', "
            "starting with a letter or digit."
        )
    return slug


def _iter_skill_files(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        relative_parts = path.relative_to(base).parts
        if any(part in SKIP_DIRS or part in SKIP_NAMES for part in relative_parts):
            continue
        files.append(path)
    return files


def _describe(foundation_id: str, path: Path, is_default: bool) -> FoundationInfo:
    files = _iter_skill_files(path)
    chars = 0
    relatives: list[str] = []
    for file_path in files:
        try:
            chars += len(file_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        relatives.append(str(file_path.relative_to(path)))
    return FoundationInfo(
        id=foundation_id,
        label=path.name or foundation_id,
        path=path,
        is_default=is_default,
        files=relatives,
        total_chars=chars,
    )


def list_foundations() -> list[FoundationInfo]:
    found: list[FoundationInfo] = []
    default_dir = _default_root()
    if default_dir.is_dir():
        found.append(_describe(DEFAULT_FOUNDATION, default_dir, True))

    root = _root()
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith(".") or child.name in SKIP_DIRS:
                continue
            if child.name == DEFAULT_FOUNDATION:
                continue
            found.append(_describe(child.name, child, False))
    return found


def get_foundation(foundation_id: str | None) -> FoundationInfo:
    wanted = (foundation_id or DEFAULT_FOUNDATION).strip()
    for info in list_foundations():
        if info.id == wanted:
            return info
    raise SkillError(f"Unknown skill foundation '{wanted}'.", 422)


def require_foundation(foundation_id: str | None) -> FoundationInfo:
    """The named foundation, or a 404 — for the write paths, where "unknown" is a missing target."""
    try:
        return get_foundation(foundation_id)
    except SkillError as exc:
        raise SkillError(exc.detail, 404) from exc


def _write_unique(directory: Path, filename: str, payload: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stem, suffix = Path(filename).stem, Path(filename).suffix
    candidate = directory / filename
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    candidate.write_bytes(payload)
    return candidate


def save_skill_file(filename: str, payload: bytes) -> tuple[str, str]:
    """Save one file into the default foundation. Returns (relative path, foundation id)."""
    require_writable()
    config = get_settings()
    if not payload:
        raise SkillError("The uploaded file is empty.")
    if len(payload) > config.skill_file_max_bytes:
        raise SkillError(
            f"File is larger than {config.skill_file_max_bytes // 1000} KB.", 413
        )

    safe_name = slugify_filename(filename or "")
    directory = _default_root()
    target = _write_unique(directory, safe_name, payload)
    return str(target.relative_to(directory)), DEFAULT_FOUNDATION


def _safe_relative(raw: str) -> str | None:
    cleaned = (raw or "").replace("\\", "/").strip().lstrip("/")
    if not cleaned or cleaned.startswith("/"):
        return None
    parts = [part for part in cleaned.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    if any(part in SKIP_DIRS or part in SKIP_NAMES for part in parts):
        return None
    if Path(parts[-1]).suffix.lower() not in ALLOWED_SUFFIXES:
        return None
    return "/".join(parts)


def _strip_common_root(paths: list[str]) -> list[str]:
    """`guidelines/a.md`, `guidelines/b.md` → `a.md`, `b.md` (folder uploads add a wrapper).

    A single file inside a wrapper folder is unwrapped too; a file at the root is left alone.
    """
    if not paths or any("/" not in path for path in paths):
        return paths
    firsts = {path.split("/", 1)[0] for path in paths}
    if len(firsts) != 1:
        return paths
    return [path.split("/", 1)[1] for path in paths]


def _materialise(name: str, pairs: list[tuple[str, bytes]]) -> FoundationInfo:
    """Write `(relative_path, bytes)` pairs into a fresh foundation directory."""
    require_writable()
    config = get_settings()
    slug = validate_slug(name)
    root = _root()
    destination = root / slug
    if destination.exists():
        raise SkillError(f"A foundation named '{slug}' already exists.", 409)
    if slug == DEFAULT_FOUNDATION:
        raise SkillError(f"'{DEFAULT_FOUNDATION}' is the built-in foundation.", 409)

    cleaned: list[tuple[str, bytes]] = []
    for raw_path, payload in pairs:
        relative = _safe_relative(raw_path)
        if relative is None:
            continue
        cleaned.append((relative, payload))
    if cleaned:
        stripped = _strip_common_root([path for path, _ in cleaned])
        cleaned = list(zip(stripped, [payload for _, payload in cleaned]))

    if not cleaned:
        raise SkillError("No .md or .txt files found in the upload.")
    if len(cleaned) > config.foundation_max_files:
        raise SkillError(
            f"Foundation has {len(cleaned)} files; the limit is {config.foundation_max_files}.", 413
        )
    total = sum(len(payload) for _, payload in cleaned)
    if total > config.foundation_max_chars:
        raise SkillError(
            f"Foundation is larger than {config.foundation_max_chars // 1_000_000} MB uncompressed.",
            413,
        )

    staging = root / f".staging-{uuid.uuid4().hex}"
    try:
        for relative, payload in cleaned:
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        staging.replace(destination)
    except OSError as exc:  # pragma: no cover - filesystem failure
        shutil.rmtree(staging, ignore_errors=True)
        raise SkillError(f"Could not write the foundation: {exc}") from exc

    return _describe(slug, destination, False)


def create_foundation_from_files(name: str, uploads: list[tuple[str, bytes]]) -> FoundationInfo:
    if not uploads:
        raise SkillError("Send either a .zip archive or the folder's files.")
    return _materialise(name, uploads)


def create_foundation_from_zip(name: str, payload: bytes) -> FoundationInfo:
    if not payload:
        raise SkillError("The uploaded archive is empty.")
    config = get_settings()
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise SkillError("That file is not a valid .zip archive.") from exc

    with archive:
        entries = archive.infolist()
        if len(entries) > config.foundation_max_files * 4:
            raise SkillError("Archive contains too many entries.", 413)

        pairs: list[tuple[str, bytes]] = []
        total = 0
        for info in entries:
            if info.is_dir():
                continue
            # Reject symlinks and anything that would escape the destination.
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                continue
            relative = _safe_relative(info.filename)
            if relative is None:
                continue
            if info.file_size > config.skill_file_max_bytes:
                raise SkillError(f"'{relative}' exceeds the per-file size limit.", 413)
            total += info.file_size
            if total > config.foundation_max_chars:
                raise SkillError("Archive expands beyond the uncompressed size limit.", 413)
            try:
                pairs.append((relative, archive.read(info)))
            except (zipfile.BadZipFile, OSError) as exc:
                raise SkillError(f"Could not read '{relative}' from the archive.") from exc

    if not pairs:
        raise SkillError("The archive contains no .md or .txt files.")
    return _materialise(name, pairs)


def delete_foundation(foundation_id: str) -> None:
    require_writable()
    if foundation_id == DEFAULT_FOUNDATION:
        raise SkillError(f"'{DEFAULT_FOUNDATION}' is the built-in foundation and cannot be deleted.", 400)
    root = _root().resolve()
    target = (root / foundation_id).resolve()
    if root not in target.parents or not target.is_dir():
        raise SkillError(f"No foundation named '{foundation_id}'.", 404)
    shutil.rmtree(target)


# ----------------------------------------------------------------------------------- evolution
#
# Skill evolution (phase 34) writes into a foundation. Everything below is deliberately strict:
# a path that leaves the foundation, or a file type the loader would never read, is refused
# before a single byte is written.


@dataclass(frozen=True)
class FileChange:
    """One approved edit: `modify` an existing file, `create` a new one, or `delete` it."""

    file_path: str
    action: str = "modify"
    content: str = ""


VALID_ACTIONS = ("modify", "create", "delete")


def sanitize_relative_path(raw: str) -> str:
    """Validate a path for writing inside a foundation. Raises `SkillError` (400) when unsafe.

    Rejects: empty paths, absolute paths, Windows drive or UNC paths, backslashes, any `..`
    segment, hidden or skipped directories, and any extension outside the whitelist.
    """
    candidate = (raw or "").strip()
    if not candidate:
        raise SkillError("A file path is required.", 400)
    if "\\" in candidate:
        raise SkillError(f"'{raw}' is not a valid file path.", 400)
    if candidate.startswith("/") or candidate.startswith("~"):
        raise SkillError(f"'{raw}' must be a relative path inside the foundation.", 400)
    if re.match(r"^[A-Za-z]:", candidate):
        raise SkillError(f"'{raw}' must be a relative path inside the foundation.", 400)

    parts = [part for part in candidate.split("/") if part not in ("", ".")]
    if not parts:
        raise SkillError(f"'{raw}' is not a valid file path.", 400)
    if any(part == ".." for part in parts):
        raise SkillError(f"'{raw}' must not point outside the foundation.", 400)
    if any(part.startswith(".") or part in SKIP_DIRS or part in SKIP_NAMES for part in parts):
        raise SkillError(f"'{raw}' points at a reserved path.", 400)
    if Path(parts[-1]).suffix.lower() not in ALLOWED_SUFFIXES:
        raise SkillError(
            f"'{raw}' is not a supported file type; use .md, .txt or .yml.", 400
        )
    return "/".join(parts)


def _resolve_inside(base: Path, relative: str) -> Path:
    """Join `relative` onto `base` and prove the result stays inside it."""
    root = base.resolve()
    target = (root / relative).resolve()
    if root != target and root not in target.parents:
        raise SkillError(f"'{relative}' must not point outside the foundation.", 400)
    return target


def read_foundation_files(foundation_id: str | None) -> dict[str, str]:
    """Every readable rule file of a foundation, keyed by its path relative to the root."""
    info = require_foundation(foundation_id)
    files: dict[str, str] = {}
    for path in _iter_skill_files(info.path):
        try:
            files[str(path.relative_to(info.path))] = path.read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            continue
    return files


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def backup_foundation(foundation_id: str | None) -> Path:
    """Copy a foundation's files into `<backups>/<name>_<timestamp>/` and return that directory.

    The backup lives outside every foundation root, so it is never loaded into a prompt.
    """
    info = get_foundation(foundation_id)
    destination = get_settings().resolved_backups_dir / f"{info.id}_{_timestamp()}"
    destination.mkdir(parents=True, exist_ok=True)
    for path in _iter_skill_files(info.path):
        relative = path.relative_to(info.path)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return destination


def _write_atomic(target: Path, content: str) -> None:
    """Write via a temporary sibling and `os.replace`, so a crash never truncates a rule file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def apply_file_changes(
    foundation_id: str | None, changes: list[FileChange]
) -> tuple[list[str], Path]:
    """Write the approved changes into a foundation in place. Returns (applied paths, backup).

    The foundation is backed up first, so every write is reversible by copying the backup back.
    """
    require_writable()
    info = require_foundation(foundation_id)
    if not changes:
        raise SkillError("There is nothing to apply.", 422)

    # Validate every path before touching the disk: a rejected path must not leave a half-applied
    # foundation behind.
    planned: list[tuple[str, str, str]] = []
    for change in changes:
        if change.action not in VALID_ACTIONS:
            raise SkillError(f"Unknown action '{change.action}'.", 422)
        relative = sanitize_relative_path(change.file_path)
        target = _resolve_inside(info.path, relative)
        if change.action in ("modify", "delete") and not target.is_file():
            raise SkillError(f"'{relative}' does not exist in '{info.id}'.", 404)
        if change.action == "create" and target.exists():
            raise SkillError(f"'{relative}' already exists in '{info.id}'.", 409)
        planned.append((relative, change.action, change.content))

    backup = backup_foundation(info.id)

    applied: list[str] = []
    for relative, action, content in planned:
        target = _resolve_inside(info.path, relative)
        if action == "delete":
            target.unlink(missing_ok=True)
            applied.append(relative)
            continue
        _write_atomic(target, content)
        applied.append(relative)
    return applied, backup


def clone_foundation(
    source_id: str | None, new_name: str, changes: list[FileChange]
) -> tuple[FoundationInfo, list[str]]:
    """Copy a foundation into a brand-new one and apply the accepted changes to the copy.

    The source foundation is never opened for writing. The new folder is built in a staging
    directory and renamed into place, so a failure leaves nothing half-created.
    """
    require_writable()
    source = require_foundation(source_id)

    name = (new_name or "").strip().lower()
    if not CLONE_NAME_RE.match(name) or len(name) > 50:
        raise SkillError(
            "A new foundation name must be kebab-case: lowercase words separated by '-'.",
            400,
        )
    if name == DEFAULT_FOUNDATION:
        raise SkillError(f"'{DEFAULT_FOUNDATION}' is the built-in foundation.", 409)
    root = _root()
    if (root / name).exists():
        raise SkillError(f"A foundation named '{name}' already exists.", 409)

    planned: list[tuple[str, str, str]] = []
    for change in changes:
        if change.action not in VALID_ACTIONS:
            raise SkillError(f"Unknown action '{change.action}'.", 422)
        relative = sanitize_relative_path(change.file_path)
        planned.append((relative, change.action, change.content))

    staging = root / f".staging-{uuid.uuid4().hex}"
    try:
        for path in _iter_skill_files(source.path):
            relative = path.relative_to(source.path)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)

        for relative, action, content in planned:
            target = _resolve_inside(staging, relative)
            if action == "delete":
                target.unlink(missing_ok=True)
                continue
            _write_atomic(target, content)

        destination = root / name
        staging.replace(destination)
    except OSError as exc:  # pragma: no cover - filesystem failure
        shutil.rmtree(staging, ignore_errors=True)
        raise SkillError(f"Could not create the foundation: {exc}") from exc

    applied = [relative for relative, action, _ in planned if action != "delete"]
    return _describe(name, root / name, False), applied
