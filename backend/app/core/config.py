from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Environment-driven application configuration."""

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://localhost:5432/code_review"
    skills_dir: str | None = None
    # Built frontend to serve from the same origin (the container image sets this).
    # Unset during development, where Vite serves the UI on :5173.
    frontend_dir: str | None = None
    # Uploaded Core Skill Foundations live here, one directory per foundation.
    foundations_dir: str | None = None
    skill_file_max_bytes: int = 2_000_000
    foundation_max_files: int = 500
    foundation_max_chars: int = 20_000_000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    ollama_timeout_s: float = 10.0
    llm_timeout_s: float = 180.0
    github_api_url: str = "https://api.github.com"
    # GitLab host used when a key does not pin its own base URL.
    gitlab_base_url: str = "https://gitlab.com"
    github_timeout_s: float = 30.0
    # Fernet key(s) for encrypting provider credentials at rest. Comma-separated: the first
    # encrypts, every entry decrypts (rotation). Never store it in the database or the repo.
    credentials_encryption_key: str | None = None
    # Serverless mode (Vercel): no migrations or orphan sweep at startup, NullPool engine,
    # read-only skills and no local Ollama. Local and Docker runs keep the default.
    serverless: bool = False
    # Invite-only deployments set this false after the first account exists.
    signup_enabled: bool = True
    # Hosted Ollama (API key auth). Local mode uses the URL stored in settings instead.
    ollama_cloud_url: str = "https://ollama.com"
    # OpenAI-compatible endpoint for the `openai:` provider (Codex/GPT models).
    openai_base_url: str = "https://api.openai.com/v1"
    # Budgets. The skill library is far larger than a prompt, so it is sampled by relevance.
    skills_max_chars: int = 80_000
    diff_max_chars: int = 60_000
    # Past `diff_max_chars` the diff is reviewed in parts instead of being truncated: each part
    # holds whole files up to this many rendered characters, at most `llm_review_concurrency` in
    # flight. A single file larger than one part gets a part of its own.
    review_unit_chars: int = 25_000
    llm_review_concurrency: int = 3
    # Upper bound on findings stored for one review, highest severity first: several parts can each
    # return a full set, and a review nobody can read is not a better review.
    review_max_findings: int = 60
    llm_max_tokens: int = 4096

    # Watches. Locally/Docker an asyncio loop checks every `watch_interval_minutes` (0 disables it);
    # serverless starts no loop and uses POST /api/watches/tick, authenticated by `watch_tick_secret`
    # (Vercel Cron sends it as the bearer token). The per-tick caps keep one tick inside a request.
    watch_interval_minutes: int = 10
    watch_tick_secret: str | None = None
    watch_max_checks_per_tick: int = 20
    watch_max_reviews_per_tick: int = 2

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def encryption_keys(self) -> tuple[str, ...]:
        """The configured Fernet key set, current key first; empty when unset."""
        raw = self.credentials_encryption_key or ""
        return tuple(part.strip() for part in raw.split(",") if part.strip())

    @property
    def resolved_database_url(self) -> str:
        """Resolve relative SQLite paths against the backend directory.

        Keeps `sqlite:///./app.db` stable no matter which cwd uvicorn is started from,
        while leaving absolute paths and non-SQLite URLs untouched.
        """
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            return self.database_url
        path = self.database_url[len(prefix) :]
        if path in ("", ":memory:") or Path(path).is_absolute():
            return self.database_url
        return f"{prefix}{(BACKEND_DIR / path).resolve()}"

    @property
    def resolved_skills_dir(self) -> Path:
        """Locate the local review-skill directory.

        An explicit SKILLS_DIR wins; otherwise prefer the repository-level
        `./code-review` folder and fall back to `backend/code-review`.
        """
        if self.skills_dir:
            candidate = Path(self.skills_dir).expanduser()
            return candidate if candidate.is_absolute() else (BACKEND_DIR / candidate).resolve()
        repo_candidate = REPO_ROOT / "code-review"
        if repo_candidate.is_dir():
            return repo_candidate
        return BACKEND_DIR / "code-review"

    @property
    def resolved_foundations_dir(self) -> Path:
        """Directory holding uploaded Core Skill Foundations (one folder each)."""
        if self.foundations_dir:
            candidate = Path(self.foundations_dir).expanduser()
            return candidate if candidate.is_absolute() else (BACKEND_DIR / candidate).resolve()
        return REPO_ROOT / "code-review-foundations"

    @property
    def resolved_frontend_dir(self) -> Path | None:
        """Built frontend directory, or None when the API runs on its own.

        Relative paths resolve against `backend/`, matching `SKILLS_DIR`.
        """
        if not self.frontend_dir:
            return None
        candidate = Path(self.frontend_dir).expanduser()
        return candidate if candidate.is_absolute() else (BACKEND_DIR / candidate).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
