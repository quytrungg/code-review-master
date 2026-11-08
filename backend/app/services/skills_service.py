"""Core Skill Foundations: discovery, upload, extraction and deletion.

The filesystem is the single source of truth — there is no table of foundations, so a folder
added or removed by hand is reflected immediately. Two roots participate:

* the configured skills directory (default `code-review/`) — the protected default foundation
* `FOUNDATIONS_DIR` (default `code-review-foundations/`) — one sub-folder per uploaded foundation
"""

from __future__ import annotations

import io
import re
import shutil
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import get_settings

DEFAULT_FOUNDATION = "code-review"
ALLOWED_SUFFIXES = {".md", ".txt"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,49}$")
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
        raise SkillError(f"Only .md and .txt files are supported (got '{name}').")
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
