# AGENTS.md — AI Code Review Assistant

Rules for changing this repo. `README.md` is for users; this file is for contributors and agents.

## 1. Rule zero — plan before code

**Write `docs/plans/phase_<N>_plan.md` before any feature or behaviour change.** No application code
until it exists — even when told to "just do it": write the plan and implement in the same turn. `N`
is the highest existing plan + 1, sorted numerically — `ls | tail -1` breaks at `phase_10`, so use
`ls docs/plans/phase_*_plan.md | sed -E 's/.*phase_([0-9]+)_plan\.md/\1/' | sort -n | tail -1`.
Sections, in order: **Objective & Scope** (in/out) · **High-Level Design** (≥1 Mermaid diagram) ·
**API Contracts & Schema** (real JSON, columns, the Alembic revision; say plainly when there is
none) · **Target File Map** (new/changed/left alone) · **Ordered Steps** (independently verifiable) ·
**Verification** (the evidence that proves it). Fix the plan in the same change when the build
diverges; behaviour changes update `README.md`/`CHANGELOG.md`, new conventions update this file.

## 2. Scoped rules

This file holds only rules that apply everywhere. Folder detail lives in `rules/` and is read on
demand:

- `backend/rules/conventions.md` — routes, schemas, ownership, error mapping, service roster,
  logging, serverless skill guards.
- `backend/rules/review-flow.md` — ingest job, `review_events` progress, startup modes, rounds and
  decisions, sync identity, anchoring, publishing.
- `backend/rules/providers-and-keys.md` — provider ids, credential resolution, masking and reveal.
- `backend/rules/database.md` — never wipe a database, schema changes, ad-hoc drift repair.
- `backend/rules/privacy.md` — PII classification, secrets, logging, the encryption key.
- `frontend/rules/conventions.md` — screens, routes, API layer, Tailwind tokens, workspace, copy.

For any file you touch, read every `rules/*.md` from the repo root down to that file's directory,
nearest last. The nearest rule wins on a conflict, and a scoped rule may tighten but never weaken
plan-first, secret handling, or "never destroy a real database". Rules are named by topic, never by
phase; fold a rule back here (and delete the copy) once it becomes general.

## 3. What it is

Local-first interactive PR review for one or more accounts: GitHub PR or GitLab MR → diff + skill
library → anchored findings → discussion → one published review. A review can be **watched**: each
new push is reviewed as a delta that links back to the review it continues. Brief:
`MASTER_PROMPT.md`; design record: `docs/plans/`.

Python 3.12 · FastAPI · SQLAlchemy 2.0 · Alembic · httpx · psycopg 3 · React 18 + TypeScript ·
Vite 5 · Tailwind. PostgreSQL by default, SQLite for tests; the VCS is GitHub or GitLab and models
are Claude, OpenAI/Codex, Ollama Cloud or a local daemon.

## 4. Layout

```
backend/app/  routes (auth, settings, keys, reviews, watches, models, skills, analytics)
              core (config, crypto) · db (session, init_db, types, encryption)
              models (+ ReviewEvent, LLMCall, ReviewWatch) · schemas
              services (roster in `backend/rules/conventions.md`)
backend/      alembic versions/ (head = newest revision) · scripts (db copy, cost backfill, keys)
              tests (pytest, temp SQLite) · rules/ (§2)
frontend/src/ pages · components (+ ui/) · context · services/api.ts · types · hooks · lib
code-review/  bundled default skill library      code-review-foundations/  uploads (gitignored)
docs/plans/   phase plans (§1); INITIATIVES.md at the root is the ranked backlog
Dockerfile · docker-entrypoint.sh   Python 3.12 image; seeds /data/code-review on first start
```

## 5. Backend

`route → service → model/session`: routes validate, call one service and map its exception to a
status; services never import FastAPI. The product contract (ingest job, progress rows, rounds,
sync, anchoring, publishing) and the API/key rules live in `backend/rules/` (§2) — read them before
touching `backend/`. Two invariants worth repeating: a review never stays `running`, and another
account's row is a `404`, never a `403`.

## 6. Database

PostgreSQL is the default (`postgresql+psycopg://localhost:5432/code_review`); SQLite is supported
and is what tests use. Alembic is the only schema source — local/Docker startup runs `upgrade head`,
serverless runs it as a release step (with `CREDENTIALS_ENCRYPTION_KEY` exported when credential rows
exist), and every revision is verified `upgrade` **and** `downgrade -1` on a scratch database.

A column one database is merely missing is an ad-hoc `ALTER` recorded in the phase plan, not a
revision; `alembic_version` stays at head. Wiping, schema-change and drift procedures are in
`backend/rules/database.md`. Copy task: `scripts/migrate_sqlite_to_postgres.py --dry-run|--truncate`.

## 7. Frontend

Screens, routes, the `services/api.ts` rule, `types/index.ts` ↔ pydantic schemas, Tailwind tokens,
the workspace layout and copy style are all in `frontend/rules/conventions.md`. Gate: `npm run build`
(`tsc -b`); there is no frontend test runner.

## 8. Testing

- pytest + `TestClient`; `conftest.py` sets a temp SQLite `DATABASE_URL` and temp skill dirs before
  importing the app, and the lifespan runs real migrations — schema drift shows up here.
- Stub at the service boundary, never the network. The signed-in session client and its per-test
  reset live in `tests/conftest.py`; `tests/fixtures.py` holds provisioning and result helpers.
- Cover HTTP contract, anchoring, persistence, guards, references, sync idempotency, round
  decisions, delta apply, multi-pass merge, and watch ticks (no-op, claim, delta, failure).
  Gate: `cd backend && pytest -q`.

## 9. Run locally

```bash
cd backend && source .venv/bin/activate      # uv venv --python 3.12
createdb code_review                         # once
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 \
  --reload-exclude 'tests/*.py' --reload-exclude 'alembic/*.py' --reload-exclude '*.db'
cd frontend && npm run dev                   # :5173, proxies /api
```

The excludes matter: uvicorn also watches the cwd, so editing a test would restart the server.
Startup logs `Database:` and `Skills:` — check those first when the app looks empty.

- **Docker**: `docker build -t code-review-master:dev .`. `/data` is the only writable volume
  (SQLite, foundations, `SKILLS_DIR=/data/code-review`, seeded by `docker-entrypoint.sh`). Leave
  `FRONTEND_DIR` unset in development so Vite serves the UI.
- **Vercel + Supabase**: `vercel.json` deploys `web` and `api` as two Services on one domain.
  `SERVERLESS=true` switches to `NullPool` + `prepare_threshold=None`, skips startup
  migrations/sweep, disables skill writes and hides `ollama-local`. Migrate once with
  `alembic upgrade head` from outside the platform.

## 10. Security

Nothing leaves the machine except the diff/prompts sent to the chosen provider. PII, credential
encryption and logging rules are in `backend/rules/privacy.md`. Two rules apply everywhere: never
print, log or commit a token, key, password or session cookie (redact as `[REDACTED]`), and
`CREDENTIALS_ENCRYPTION_KEY` lives in the environment only — never in the database, a migration, a
commit or a log line.

## 11. Definition of done

Plan matches the code · `pytest -q` green · `npm run build` green if the UI changed · schema
round-trips up/down · feature exercised for real with plain evidence (counts, payloads, status
codes) · README/CHANGELOG/AGENTS updated · no dead code, debug output, secrets or leftover fixtures ·
no destructive command against the operator's data.

## 12. Gotchas

- `--reload-dir app` does not stop uvicorn watching the cwd; exclude globs like `tests/*.py`.
- `#N` is per review, not a global id, and filtering must not renumber it.
- A GitHub reply threads only once `github_root_comment_id` is known; if posted ids cannot be read
  back, later replies wait.
- GitLab has no "review with N comments": one discussion per finding using the MR `diff_refs`, and
  approval is best-effort.
- Summarisation is best-effort: on failure, publish the last message per thread plus a warning.
- Keep SSE headers (`Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`).
- Serverless: `asyncio.create_task` dies with the response, so ingest is a background task; progress
  must stay in `review_events`; never run `fail_orphaned_reviews()` where instances share a DB.
- **A running Vite dev server never re-reads `tailwind.config.js`.** HMR swaps components (a new
  button appears) while the CSS keeps the old tokens, so a class/attribute can flip with no visual
  change. Restart `npm run dev` after touching the config or the palette (phase 37).
- **Two names for one provider.** A stored credential has `key.provider == "ollama_local"` (database
  form); a model id is `"ollama-local:<tag>"` (hyphen). Comparing the two silently never matches —
  that is how "hide local Ollama on serverless" quietly stopped hiding it. Use
  `llm_service.DB_PROVIDER[...]` when reading a key row, the prefix when reading a model id.
- A watch advances `last_seen_commit_id` when its delta review is **created**, not when it succeeds;
  a rejected duplicate advances it too, so a watch can never park on one commit forever.
- This is a git repository (`main` tracks `origin/main`): read `git status`/`git log` before
  assuming history, and commit only when asked.
