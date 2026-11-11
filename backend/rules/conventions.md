# Backend rules

Applies to everything under `backend/`. Root `AGENTS.md` governs; these are the local details that
would be noise at the repo root.

`route → service → model/session`: a route validates, calls one service and maps its exception to a
status; services never import FastAPI. The review contract lives in `review-flow.md`, providers and
keys in `providers-and-keys.md`, data safety in `database.md`, PII in `privacy.md`.

## Services

`vcs` (fetch/publish dispatch by host) · `github_service` · `gitlab_service` · `keys_service` ·
`diff_parser` · `skill_loader` · `skills_service` · `prompts` · `llm_service` · `review_pipeline` ·
`review_units` (packs a large diff into per-file parts) · `watch_service` (watches, ticks,
delta reviews) · `thread_sync` · `discussion` ·
`references` (`#N`) · `summarise` · `verdict` · `apply_service` · `progress` ·
`auth_service` · `secrets`, `settings_service` · `ledger` (one `llm_calls` row per call, own
session, never raises) · `analytics` (the `/api/analytics` aggregates and a review's usage line) ·
`github_inbox_service` (PR inbox: search-based discovery, turn-taking detection, quick reviews,
comment polish) · `skill_analyzer_service` (skill evolution: aggregates the review history,
asks a model to propose guideline edits, validates them against the filesystem).

## Routes and errors

- **Errors** are mapped at the route boundary: `PipelineError(detail, status_code)`, `SkillError`,
  `GitHubError`, `LLMError` → `400` malformed or nothing accepted · `404` unknown review/model/round
  · `409` everything already applied, duplicate foundation · `422` unusable request · `502`
  upstream. Connection probes return `ok: false` + detail, never a 5xx.
- **New route modules** live in `app/api/routes/` and must be mounted in `app/api/router.py`
  (`api_router.include_router(...)`), or they simply do not exist.
- **Routes return pydantic models**, never ORM objects. If a response needs a field, add it to the
  schema in `app/schemas/` and build it with a `from_row`-style classmethod.
- **Every new route is owned.** Non-auth routes are mounted with `Depends(get_current_user)` in
  `app/api/router.py` and take `user: CurrentUser`; pass `user.id` into the service and filter by it.
  Another account's row is a `404`. Public routes belong only to `/api/auth/*`, `/api/health` and
  `POST /api/watches/tick` — the last because a cron job cannot hold a session cookie: it
  authenticates with `WATCH_TICK_SECRET` (`hmac.compare_digest`, `503` when the secret is unset) and
  must never be moved behind or in front of the session dependency by accident.
- **A new service module** is added to the roster above in the same change.
- **Serverless skills are read-only** — `skills_service.require_writable()` raises
  `SkillError(..., 403)`, `GET /api/skills` reports `uploads_enabled: false`, and the UI hides write
  controls. The bundled `code-review/` library is the source there; runtime uploads need object
  storage (phase 21).

## Services and background work

- **Background work** opens its own `SessionLocal()` inside the task (the request session is closed
  by then) and must publish progress events; see `app/services/review_pipeline.py`.
- **Network calls are always inside a service function** in an `app.services.*` module, so a test can
  monkeypatch `app.services.<module>.<function>` instead of mocking HTTP.
- **Logging** uses a module-level `logger = logging.getLogger(__name__)`; never `print`, never log a
  secret, prompt or full diff.

## Costs

`app/core/pricing.py` is the only price source: published list prices per 1M tokens, matched by
model prefix, standard tier only. `ollama-local` is in `FREE_PROVIDERS` because it runs on the
operator's hardware; every hosted provider — Ollama Cloud included, metered since 2026-08-31 — is
priced. A model with no row returns `None` (the UI shows `—`), never `0`. When a row already in the
ledger is mispriced, the repair is `scripts/backfill_llm_costs.py` (dry run by default), recorded in
the phase plan — not a migration.

## Schema and time

- **Alembic revisions** are `alembic/versions/NNNN_slug.py` with `revision = "NNNN"` matching the
  filename prefix and `down_revision` pointing at the previous one. Hand-edit; never auto-generate a
  schema change without reviewing the produced DDL.
- **Timestamps** come from `app.db.base.utcnow`; never call `datetime.now()` without a timezone.
