# AI Code Review Assistant

A local-first, interactive pull-request reviewer. Point it at a GitHub PR, let a model review
the diff against **your own review standards** — **Ollama Cloud** (default, API key), **Claude**,
or a **local Ollama daemon** — argue with it in a side-by-side workspace, then publish the agreed
conclusion back to GitHub as one review with inline comments.

Nothing leaves your machine except the diff you send to the model you choose. Credentials,
reviews, threads and conversations live in your own PostgreSQL database.

```
GitHub PR  ──►  diff parser  ──►  skill library + prompt  ──►  Ollama Cloud / Claude / local
                                        │                            │
                                        ▼                            ▼
                              anchored findings (file:line)  ◄── JSON findings
                                        │
                          ┌─────────────┴─────────────┐
                          ▼                           ▼
              split-pane workspace            bulk discussion
              (code ↔ comment cards)          (one call per thread)
                          │                           │
                          └─────────────┬─────────────┘
                                        ▼
                        one GitHub review: event + inline comments
```

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Docker](#docker)
- [Vercel + Supabase](#vercel--supabase)
- [Configuration](#configuration)
- [Usage](#usage)
- [API reference](#api-reference)
- [Data model](#data-model)
- [How a review is produced](#how-a-review-is-produced)
- [Project structure](#project-structure)
- [Development](#development)
- [Design notes and limitations](#design-notes-and-limitations)
- [Troubleshooting](#troubleshooting)

## Features

**Credentials and providers**

- **Accounts**: sign up with an email and password at `/signup`, sign in at `/login`. Every account
  owns its own version-control keys, model keys, active selection and reviews; another account's
  review id is a `404`, never a `403`. Passwords are salted PBKDF2-SHA256 hashes, sessions are
  HttpOnly cookies whose tokens are stored only as SHA-256 digests (14-day expiry).
- **Two credential families, one row per provider**: `version_control_keys` (GitHub or GitLab
  tokens, optional base URL for self-hosted instances) and `llm_keys` (Claude, OpenAI/Codex,
  Ollama Cloud, Ollama local). `settings` only stores which key is **active** in each family, so a
  GitHub and a GitLab token — or a Claude and a local Ollama — can coexist.
- Credentials are returned **masked** (`ghp_••••••••cdef`); raw values only with `?reveal=true`.
- **Ollama Cloud is the default model provider**: hosted models at `https://ollama.com/api` with an
  API key. A **local daemon** stays available as a separate provider (`ollama-local:`), so both can
  be configured at once.
- Connection tests per key that report failures as data (`ok:false` + detail), never a 5xx.
- Model dropdown built from the configured keys: cloud/local Ollama tags, Anthropic and OpenAI
  model lists (with static fallbacks), plus a `preferred` model from the active key.
- **First-run guide**: until a version-control key *and* a model key are active, `/` redirects to
  `/setup`, which walks through both steps with live tests before unlocking the dashboard.

**Review generation**

- GitHub REST ingestion: PR metadata (title, HEAD SHA, state, author) plus the unified diff.
- A real diff parser: per-file hunks, RIGHT-side line numbers, binary/lockfile/vendored files
  skipped with a recorded reason.
- Local skill injection from `code-review/` — 26 rule files, always including the entry
  file, then ranked by relevance to the changed paths to fit an 80k-character prompt budget.
- Strict JSON output contract, tolerant parsing (fences, prose, wrapped objects), and schema
  validation per finding.
- **Line anchoring**: every finding is mapped onto a real RIGHT-side diff line (nearest line
  wins, unknown files are dropped with a warning), and the code context is rebuilt from the
  true diff so neither the UI nor GitHub ever sees an invented hunk.

**Interactive workspace**

- 50/50 split pane: syntax-toned diff boxes on the left, markdown discussion cards on the right,
  linked selection in both directions, matching ordinals (`#1`, `#2`, …).
- **Live progress**: review creation returns immediately and streams every stage over SSE
  (\"Fetching pull request…\", \"Reading skill files — 8 of 26 from code-review\", \"Asking gemma4:31b…\",
  \"Anchoring findings\"). The header fills in the PR identity as soon as it is known.
- Typing is local-only: drafts live in React state and no request is made until you submit.
- **Copy context** on the discussion card puts `path:line` plus the diff hunk on the clipboard;
  the copy icon beside the file name in the code panel copies just the path.
- The PR title carries an open-in-GitHub link, so the pull request is one click away before
  anything has been published.
- Bulk submit sends every unsent draft in one request; the backend fans out one model call per
  thread concurrently, so one failing thread does not lose the others' replies. Typing `#` opens a
  picker of this review's threads (`#2 · app/models/user.rb:6 · excerpt`): digits filter it,
  `↑`/`↓` move, `Enter`/`Tab` or a click insert `#N`, `Esc` closes. The current thread is not
  offered.

**Skill management**

- **Skills tab (`/skills`)**: browse the library, upload a single `.md`/`.txt` into the default
  `code-review/` folder, or create a **Core Skill Foundation** from a folder or a `.zip`
  (server-side extraction with traversal, symlink, entry-count and size guards).
- The dashboard's new-review panel picks the foundation per review (default: the original
  folder); the choice is stored on the review and reused for its discussions.

**Existing pull-request threads**

- **Import at ingest**: every review comment already on the PR is fetched, grouped by its root
  comment (`in_reply_to_id` chains are walked up), and stored as a `GITHUB_EXISTING` thread with the
  file, line, hunk, author and the whole conversation. They sit beside the AI findings, not apart.
- **One kind of thread, rounds inside it**: each inbound comment opens a round; the copilot
  scratchpad answers it; the round is accepted (which writes the GitHub comment), published, or
  closed with
  *resolve without reply*. Historical rounds collapse to `Round N · Published`.
- **Sync GitHub** fetches the PR's comments again, appends unseen replies as new rounds, spawns a
  thread for unseen top-level comments, and ignores comments your own token posted. Deduplication is
  by GitHub comment id, so running it twice changes nothing.
- **Delta apply**: only pending work is published. Unposted AI findings travel as one formal review
  (the GitHub comment ids are read back so later replies thread correctly); queued rounds are posted
  as replies inside their own conversations. Nothing is posted twice, and an apply with nothing
  pending is a `409` — unless the event is `APPROVE`, which publishes an approval with no comments.
- **Filter bar** (`All` / `AI Findings` / `GitHub Threads` / `Needs Response`) with live counts;
  AI cards carry a violet rail and `🤖 AI Finding #N`, imported threads a slate rail and
  `🐙 GitHub Discussion #N · by @author`. Filtering never renumbers.

**The review loop**

- **Watch a pull request**: one button in the review header watches that PR with the review's model
  and foundation. Every ten minutes a check compares the PR head with the commit the watch has
  already accounted for; an unchanged head is a no-op.
- **Delta review on a new push**: only `compare(last_seen…head)` is reviewed, as a new review that
  says \"Continues review #N\", is badged **Delta review**, and warns in its notes that the earlier
  review's threads were not re-validated. Findings that survived the push are not re-raised.
- **Two schedulers, one service**: locally an asyncio loop ticks every `WATCH_INTERVAL_MINUTES`;
  on Vercel a cron calls `POST /api/watches/tick`, which is secret-authenticated and answers `503`
  when no secret is configured. Two ticks racing can never produce two reviews for one commit.
- **Watched pull requests** on the dashboard: head, last check, last error, a link to the latest
  review, and Pause / Resume / Delete.

**Review intelligence**

- **`#N` cross-references**: mention another thread in a comment; the backend resolves it to that
  thread's file, line, finding and latest conclusion and feeds it to the model. Typing `#` opens a
  picker of this review's threads (digits filter, ↑/↓ move, Enter/Tab/click insert) that opens above
  or below the composer without leaving the discussion pane. Chips in the UI jump to the referenced
  thread.
- **AI verdict + confidence** stored per review and shown in the action bar with a one-click
  \"use it\" that adopts the suggestion. It is **recomputed after every discussion submit** — the
  model re-reads all threads (including withdrawn ones) and returns a verdict, confidence and a
  one-line rationale; a failed pass keeps the previous opinion and reports a warning.
- **Summarise + prune before publishing**: one model pass rewrites each thread as a standalone
  GitHub comment and can withdraw findings the model conceded on. Withdrawn threads are not
  posted; if the pass fails, publishing still happens with the last message of each thread.
- **No review body.** Apply publishes the inline comments only, so a review carries exactly the
  findings you accepted — nothing is posted until a finding is accepted. The one exception is an
  approval: an `APPROVE` with nothing accepted submits an approval with no comments, like the
  GitHub UI's own button.

**Publishing**

- Verdict selector (`REQUEST_CHANGES` / `APPROVE` / `COMMENT`) plus an optional summary.
- Inline comments are re-validated against the **current** PR diff before posting, because a
  moved branch would otherwise make GitHub reject the entire review.
- No silent summary-only fallback: if every comment is pruned or rejected, the apply returns
  `422`/`502` and posts nothing, rather than publishing a comment review with nothing in it.
- An approval needs no findings. With `APPROVE` selected and nothing accepted, the apply button
  reads **Approve on GitHub** and submits an approval with no inline comments; `COMMENT` and
  `REQUEST_CHANGES` still require something to say.
- Applied reviews record the verdict and the GitHub review URL. Applying again is allowed when
  something is pending (a queued reply, or findings added since) and posts only that; with nothing
  pending it is a `409`.
- Ingestion warnings (skipped files, truncation, dropped findings) are surfaced in the UI.

**Telemetry and analytics**

- **Every model call is recorded** — purpose, provider, model, prompt/completion tokens, estimated
  cost, latency and outcome — in `llm_calls`. Counts only: no prompt, diff or completion is ever
  stored there.
- **Usage line per review**: `4 calls · 61.1k tokens · ~$0.09 · 2m 14s total` beside the model
  badge, refreshed after every discussion, decision and apply.
- **Dashboard strip**: 30-day spend, tokens, acceptance rate and median latency above the review
  list, with a link to the full page.
- **`/analytics`**: KPI cards, a model comparison table (calls, tokens in/out, est. cost, average
  latency, acceptance and push-back rates), a purpose breakdown (ingest / discuss / verdict /
  summarise) and soft monthly token/dollar caps with an 80% warning and a 100% red state.
- **Costs are estimates** from `app/core/pricing.py`, matched by model prefix at the provider's
  published list price. Ollama Cloud has been billed per token since 2026-08-31, so its calls are
  priced like Claude's; `ollama-local` reports `~$0.00` because it runs on your own hardware. A model
  with no published price reports tokens and `—` for money rather than a made-up number. Standard
  rates only: off-peak and cached-input discounts are not modelled.
- **A ledger failure never breaks a review**: the insert runs in its own session and a failure is a
  logged warning.

## Requirements

| Piece | Version | Notes |
|---|---|---|
| Python | 3.12 | backend, tested on 3.12.12 (the version Vercel runs) |
| Node.js | 18+ | frontend (Vite 5) |
| Version-control token | — | GitHub (classic `repo` scope, or fine-grained PR read/write) **or** a GitLab PAT with `api` scope |
| Model | — | an **Ollama Cloud API key** (default), an Anthropic key, or a local Ollama daemon |
| PostgreSQL | 14+ | the application database (`psycopg` 3 ships in `requirements.txt`) |
| Docker | 24+ | optional; one image carries the API, the compiled UI and the skill library |

SQLite is still supported — the test suite runs on it, and `DATABASE_URL=sqlite:///./app.db`
gives you a throwaway local database — but PostgreSQL is the default target.

## Quick start

### 1. Backend

```bash
cd backend
uv venv --python 3.12 .venv && source .venv/bin/activate    # or: python3.12 -m venv .venv
uv pip install -r requirements.txt                           # or: pip install -r requirements.txt
createdb code_review                                        # or: psql -c "create database code_review"
cp .env.example .env                                        # DATABASE_URL postgresql+psycopg://localhost:5432/code_review
uvicorn app.main:app --reload --reload-exclude 'tests/*.py' --reload-exclude 'alembic/*.py' \
  --reload-exclude '*.db' --port 8000
```

The schema is created on the first boot: startup runs `alembic upgrade head`, so the four tables
appear in `code_review`. The `--reload-exclude` flags matter: uvicorn always watches the working
directory in addition to any `--reload-dir`, so without them editing a test would restart the
server (and reset an in-flight SSE stream). You can also run migrations by hand:

```bash
alembic upgrade head      # apply
alembic downgrade base    # roll everything back
```

The connection is `DATABASE_URL` in `backend/.env` (pydantic-settings reads it automatically).
Relative SQLite paths resolve against `backend/`; for an absolute SQLite file use four slashes,
`sqlite:////Users/you/data/app.db`.

- API: <http://127.0.0.1:8000/api/health>
- Interactive docs: <http://127.0.0.1:8000/docs>

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to `127.0.0.1:8000`, so no CORS setup or
`.env` is needed in development. (Vite binds `localhost`; on machines where that resolves to
IPv6, use `npm run dev -- --host 127.0.0.1` if you need `127.0.0.1:5173` literally.)

### 3. First review

On first boot the app opens `/setup` instead of the dashboard:

1. **Version control** → pick **GitHub** or **GitLab**, paste a token (GitLab also takes a base URL
   for a self-hosted instance). It is saved, activated and tested immediately.
2. **Model provider** → **Ollama Cloud** (default) needs an API key from
   <https://ollama.com/settings/keys>; **Claude** and **OpenAI/Codex** take their keys;
   **Ollama (local)** needs only a base URL. Any of them can coexist.
3. **Go to reviews** unlocks once the server reports `needs_setup: false`.

Then paste `https://github.com/owner/repo/pull/123` or a GitLab merge-request URL
(`https://gitlab.com/group/project/-/merge_requests/12`), pick a model, and press **Start review**.
Credentials are managed later in **Settings**, where each family keeps a list and the active one is
what the next review uses.

## Docker

One image carries the API, the compiled UI and the default skill library. FastAPI serves the built
SPA itself, so the browser talks to one origin and the session cookie and SSE stream need no proxy.

```bash
docker build -t code-review-master:dev .
docker run --rm -p 8000:8000 -v code-review-data:/data code-review-master:dev
```

Open <http://127.0.0.1:8000>. The image defaults to SQLite at `sqlite:////data/app.db` inside the
`/data` volume and creates the schema with `alembic upgrade head` on first boot. To use PostgreSQL
instead, override `DATABASE_URL`:

```bash
docker run --rm -p 8000:8000 -v code-review-data:/data \
  -e DATABASE_URL=postgresql+psycopg://user:pass@host.docker.internal:5432/code_review \
  code-review-master:dev
```

- `/data` holds everything writable: the SQLite database, the uploaded Skill Foundations, and the
  default skill library at `/data/code-review`. On first start `docker-entrypoint.sh` copies the
  bundled `code-review/` from the image into that volume, so a single-file upload or a hand edit
  survives a restart. An existing volume is never overwritten by an upgrade — copy new rules in, or
  remove the volume to re-seed it.
- Progress events are rows in the database (`review_events`), so a second uvicorn worker no longer
  splits the SSE stream. One worker is still the simplest deployment.
- `FRONTEND_DIR` is what makes FastAPI serve the built SPA (`/app/frontend/dist` in the image). It
  is unset in a development checkout, where Vite serves the UI and proxies `/api`.
- The container runs as uid `10001`; a bind-mounted `/data` must be writable by that user.
- The image binds `0.0.0.0:8000`. Pass `-e CREDENTIALS_ENCRYPTION_KEY=…` (or `--env-file backend/.env`):
  provider tokens are encrypted at rest, and a container started without the key on a database that
  already holds credentials fails its startup migration instead of running unencrypted.

## Vercel + Supabase

`vercel.json` deploys two services in one project: `web` (the Vite SPA) and `api` (FastAPI, Python
3.12) on one domain, with `/api/*` routed to the API. Same origin keeps the session cookie and the
SSE stream working without CORS or an API base URL.

1. Create the Supabase project and copy the **transaction pooler** connection string (port 6543).
   Rewrite the scheme to `postgresql+psycopg://` and keep `?sslmode=require`:
   `postgresql+psycopg://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:6543/postgres?sslmode=require`
2. Set the Vercel environment for **Production**: `DATABASE_URL` (above), `SERVERLESS=true`,
   `CREDENTIALS_ENCRYPTION_KEY` (the same generator as local), `SIGNUP_ENABLED=true` for the first
   boot, `CORS_ORIGINS=https://<production-domain>`. Leave `SKILLS_DIR`, `FOUNDATIONS_DIR` and
   `FRONTEND_DIR` unset.
3. Run the migrations once from a laptop or CI, with the key exported so `0011` can encrypt any
   credential rows it finds (a fresh database needs no key):
   `cd backend && CREDENTIALS_ENCRYPTION_KEY=… DATABASE_URL=<pooler-url> alembic upgrade head`
4. Deploy, open the app, create the operator account, then set `SIGNUP_ENABLED=false` and redeploy.
5. Disable the Supabase Data API (or enable RLS with no policies): only the API should reach the
   tables.

What differs on Vercel:

- **Migrations are a release step, not startup.** `SERVERLESS=true` skips `alembic upgrade head`
  and the orphan sweep, because another instance may own a running review; a review older than ten
  minutes is failed when it is next read.
- **The filesystem is read-only.** The bundled `code-review/` library is the only source of skill
  files: `POST /api/skills/files`, `POST /api/skills/foundations` and the delete endpoint return
  `403`, `GET /api/skills` reports `uploads_enabled: false`, and the Skills page hides the write
  controls. Add markdown to the repository and redeploy to change the library; runtime uploads
  return with object storage (`docs/plans/phase_21_plan.md`).
- **Local Ollama is unavailable.** `ollama-local:` models are rejected with `422` and hidden from
  `/api/models`; use Claude, OpenAI or Ollama Cloud.
- **Ingest runs after the response as a background task**, and progress is read from
  `review_events`, so a review created without an open tab still finishes and a late tab replays
  every stage.
- **Watches tick from a cron, not a loop.** No loop starts when `SERVERLESS=true`; `vercel.json`
  schedules `POST /api/watches/tick` every ten minutes and the platform sends `CRON_SECRET` as a
  bearer token, so set `CRON_SECRET` and `WATCH_TICK_SECRET` to the **same** value. Leaving
  `WATCH_TICK_SECRET` unset makes the endpoint answer `503`, which is the safe default.

## Configuration

Backend reads `backend/.env` (see `backend/.env.example`). Every value has a working default.

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://localhost:5432/code_review` | Any SQLAlchemy URL. `sqlite:///./app.db` still works for throwaway runs; relative SQLite paths resolve against `backend/`. |
| `SERVERLESS` | `false` | Vercel mode: `NullPool` + no prepared statements, no startup migrations or orphan sweep, read-only skills, no `ollama-local`. |
| `SIGNUP_ENABLED` | `true` | Set `false` after the first account on a public deployment; `POST /api/auth/signup` then returns `403`. |
| `CREDENTIALS_ENCRYPTION_KEY` | unset | Fernet key(s) encrypting `version_control_keys.token` and `llm_keys.api_key` at rest. Comma-separated: the first encrypts, every entry decrypts. Generate with `python scripts/generate_encryption_key.py`; required once a credential row exists. |
| `SKILLS_DIR` | repo `./code-review` | Root of the default skill library (`.md`/`.txt`, recursive). |
| `FRONTEND_DIR` | unset | Built SPA to serve from FastAPI at `/` (the image sets `/app/frontend/dist`). Unset = API only. |
| `FOUNDATIONS_DIR` | repo `code-review-foundations` | Where uploaded Core Skill Foundations are stored, one folder each. |
| `SKILL_FILE_MAX_BYTES` | `2000000` | Per-file upload cap. |
| `FOUNDATION_MAX_FILES` | `500` | Max rule files in one uploaded foundation. |
| `FOUNDATION_MAX_CHARS` | `20000000` | Max uncompressed size of a foundation. |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated allowed origins. |
| `GITHUB_API_URL` | `https://api.github.com` | Default GitHub API base when a key does not pin one (Enterprise or a mock). |
| `GITLAB_BASE_URL` | `https://gitlab.com` | Default GitLab host when a key does not pin one. |
| `GITHUB_TIMEOUT_S` | `30` | GitHub request timeout. |
| `OLLAMA_TIMEOUT_S` | `10` | Ollama probe timeout. |
| `OLLAMA_CLOUD_URL` | `https://ollama.com` | Hosted Ollama endpoint used when a cloud key has no base URL. |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint for the `openai:` provider. |
| `LLM_TIMEOUT_S` | `180` | One model call (local models can be slow). |
| `SKILLS_MAX_CHARS` | `80000` | System-prompt budget for the skill library. |
| `DIFF_MAX_CHARS` | `60000` | Diff budget for a whole review. Past it the change is reviewed in parts instead of being truncated. |
| `REVIEW_UNIT_CHARS` | `25000` | Rendered characters per part once a diff exceeds `DIFF_MAX_CHARS`. Files are never split; one file larger than a part gets a part of its own. |
| `LLM_REVIEW_CONCURRENCY` | `3` | Parts reviewed at once. Raise it for a hosted provider, lower it for a single local GPU. |
| `REVIEW_MAX_FINDINGS` | `60` | Findings kept per review after merging the parts, highest severity first. |
| `WATCH_INTERVAL_MINUTES` | `10` | How often the local watch loop checks for new commits; `0` disables the loop. |
| `WATCH_TICK_SECRET` | unset | Shared secret for `POST /api/watches/tick`. Unset disables the endpoint (`503`), which is what makes it safe to expose. |
| `WATCH_MAX_CHECKS_PER_TICK` | `20` | Watches examined per tick, oldest check first. |
| `WATCH_MAX_REVIEWS_PER_TICK` | `2` | Delta reviews started per tick, so one cron invocation stays inside `maxDuration`. |
| `LLM_MAX_TOKENS` | `4096` | Claude output cap. |

### Credential encryption

GitHub/GitLab tokens and model-provider keys are encrypted at rest with authenticated symmetric
encryption (Fernet: AES-128-CBC + HMAC-SHA256) and stored as `enc:v1:<token>`; the key lives in
`CREDENTIALS_ENCRYPTION_KEY` and never in the database. A stolen `pg_dump`, `app.db` or volume
snapshot is therefore useless without the environment. It does **not** protect a compromised host, a
leaked `.env` or API access to the running app.

```bash
cd backend
python scripts/generate_encryption_key.py   # prints one key, paste into .env
alembic upgrade head                        # encrypts existing plaintext rows (0011)
```

- The upgrade **refuses to run** while plaintext rows exist and no key is configured, so a database
  is never left claiming encryption it does not have.
- Back the key up separately from the database. Losing it is not recoverable: every stored
  credential has to be re-entered. With the key, a stolen dump can be decrypted.
- Rotation: set `CREDENTIALS_ENCRYPTION_KEY="<new>,<old>"`, restart, run
  `python scripts/rotate_credentials_key.py --dry-run` then without the flag, remove `<old>`, restart.
- Copying an old SQLite database into PostgreSQL encrypts the copied rows inside the copy
  transaction, so the target never holds plaintext.

### Moving an existing SQLite database to PostgreSQL

`backend/scripts/migrate_sqlite_to_postgres.py` copies every table across (rake-style, one
command). It refuses to write into a non-empty target unless told to, runs the Alembic migrations
on the target first, copies inside one transaction, resets the id sequences, then re-counts both
sides and rolls back on any mismatch. SQLite's naive timestamps were stored as UTC, so they are
re-attached as UTC on the way in rather than being reinterpreted in the server's local zone.

```bash
cd backend
python scripts/migrate_sqlite_to_postgres.py --dry-run     # what would move
python scripts/migrate_sqlite_to_postgres.py --truncate    # source defaults to backend/app.db
python scripts/migrate_sqlite_to_postgres.py \
  --source sqlite:////Users/you/old/app.db \
  --target postgresql+psycopg://localhost:5432/code_review
```

`--target` defaults to `DATABASE_URL`. Use four slashes for an absolute SQLite path. Exit codes:
`0` success, `1` for a missing source, a SQLite target, or a non-empty target without
`--truncate`.

## Usage

### Settings

- Secrets are shown masked with a `Configured` badge. **Replace** opens an input, **Clear**
  marks the value for deletion, and nothing is written until **Save changes**.
- **Discard** resets the form to the last saved state (it re-reads the server, it does not
  unsave anything).
- The Ollama card has a **Cloud / Local daemon** switch. Cloud takes an API key (the default),
  Local takes a base URL plus a default model. Switching keeps the stored key, so toggling back
  does not require re-entering it.
- Ollama base URL is validated as a URL and trailing slashes are normalised.

### Setup guide (`/setup`)

Shown automatically while `needs_setup` is true (no GitHub token, or no model credential). It
is also reachable deliberately. Each step saves and tests in one action, and the page steps
aside as soon as both requirements are met — after that the dashboard is the landing page.

### Skills (`/skills`)

- **Default foundation** shows its file count, size and file list; a single `.md`/`.txt` can be
  uploaded straight into it (2 MB cap, slugified filename, duplicates get `-2`).
- **Core Skill Foundations** lists uploaded folders with per-file previews and a delete action.
  A new one is created from a folder or a `.zip`; the server strips one shared wrapper folder,
  keeps only `.md`/`.txt`, and rejects traversal, symlinks, oversized archives and empty results.
- Pick a foundation in the new-review panel; the dashboard badge shows how many files it has.
- On a read-only deployment (Vercel) the page lists the bundled library and hides upload, create
  and delete: markdown ships with the repository there. `GET /api/skills` reports
  `uploads_enabled: false`.

### Applying a review

- The footer shows the model's verdict and confidence with a **use it** action, and a live preview
  of the exact PR body that will be posted.
- **Apply to GitHub** runs the summarise/prune pass, then publishes. Threads the model withdrew
  are marked `withdrawn`, excluded from the payload, and reported in the notice and ingestion
  notes.

### Watching a pull request

- **Watch for new commits** in the review header (or `POST /api/watches {review_id}`) watches that
  PR with the review's model and foundation. One watch per PR per account; pressing it again
  resumes a paused watch instead of adding a second one.
- Every ten minutes (`WATCH_INTERVAL_MINUTES`) the check reads the PR head. An unchanged head is a
  no-op; a moved one reviews `compare(last_seen…head)` only and opens a **linked review** that says
  “Continues review #N”, carries `trigger=watch`, and warns that the earlier review's threads were
  not re-validated. The next push continues from that review.
- **The delta is reviewed, nothing older.** A finding that survived the push is not re-raised, and
  a comment on a line the delta did not touch cannot be posted to it — apply already drops stale
  anchors with a warning.
- `last_seen_commit_id` advances when the review is created, not when it succeeds: a failed delta
  review stays visible as `failed` and the watch keeps moving, instead of re-reviewing the same
  commit on every tick.
- **Watched pull requests** on the dashboard lists every watch with its head, last check, last
  error, a link to the latest review, and Pause / Resume / Delete.

### Dashboard

- **New code review**: PR URL + model. The dropdown is disabled when no provider is reachable,
  with an inline hint about what to fix.
- **Review history**: title, repo, model, status badge (`Draft`, `In discussion`, `Applied`)
  and relative time. Failed ingests remain visible so the error can be inspected.
- **30-day activity bar** above the list: estimated spend, tokens, acceptance rate and median
  latency. It turns amber at 80% of a monthly cap and red at 100%; neither ever blocks a review.

### Analytics (`/analytics`)

- KPI cards: estimated spend in the window, tokens processed, median/p95 latency and the acceptance
  rate, each with the counts behind it.
- **Model comparison** table: calls, tokens in/out, estimated cost, average latency, acceptance and
  push-back. Acceptance counts AI findings whose latest round was published; push-back counts the
  ones you replied to or discarded. Imported GitHub threads are not the model's work and are
  excluded.
- **Purpose breakdown**: ingest, discuss, verdict and summarise, by calls and tokens.
- **Monthly budget**: token and dollar caps, stored on your settings row. Saving an empty field
  clears that cap. Caps warn, they never block; the window selector (7/30/90 days) does not affect
  the monthly budget calculation.

### Workspace (`/reviews/:id`)

- Filter bar above both panes: `All (n)`, `🤖 AI Findings (n)`, `🐙 GitHub Threads (n)`,
  `⚠️ Needs Response (n)`. The badge ordinal is the review-wide `#N` and does not change when you
  filter.
- Left pane: one code box per thread — file path, `L<line>` badge, the anchored hunk with
  `+`/`-`/context colouring and lightweight token highlighting. A violet rail marks an AI finding,
  a slate rail an imported discussion.
- Right pane: the thread's rounds. The active round shows the inbound comment, the conversation and
  the composer; older rounds collapse to `Round N · Published`. A card shows `unsent` while it holds
  a draft and `⚠️ Needs response` when a new inbound comment is waiting.
- Every round offers the same two choices, **Accept** and **Push back**. Accepting runs one model pass
  that rewrites the thread into the GitHub comment for that round — first-round findings keep their
  severity prefix, replies answer the inbound comment — and shows it in an editable box: adjust the
  wording and **Save changes** before **Apply**. Push back publishes nothing for the round and
  withdraws the finding when it is an AI thread's first round. Discussing a closed round opens a new
  draft round automatically.
- Clicking a code box scrolls and highlights its card (and vice versa); `Esc` clears the
  selection.
- The action bar is always visible: unsent count, verdict selector, AI opinion, **Submit
  responses**, and **Apply N pending findings / replies** (disabled until something is accepted and
  not yet posted). With nothing accepted and `APPROVE` selected it becomes **Approve on GitHub**.
- **Sync GitHub** in the header pulls new comments; GitLab reviews show it disabled with the reason.

## API reference

Base path `/api`. All bodies are JSON. Everything except `/auth/*`, `/health` and
`POST /watches/tick` requires the `acr_session` cookie and returns `401 {"detail":"Sign in to
continue."}` without it; every row read or written is scoped to the signed-in account. The tick is
the one cron-facing endpoint: it authenticates with a shared secret instead of a cookie.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/signup` | `{email, password}` → `201`, account + session cookie (`409` duplicate, `422` invalid) |
| `POST` | `/auth/login` | `{email, password}` → `200` + session cookie (`401` when wrong) |
| `POST` | `/auth/logout` | Revoke the session and clear the cookie (`204`) |
| `GET` | `/auth/me` | `{id, email, created_at}` for the signed-in account |
| `GET` | `/health` | `{"status": "ok"}` (public) |
| `GET` | `/settings` | Active key per family, masked. `?reveal=true` adds raw values. |
| `PUT` | `/settings` | Select the active key; set `monthly_token_budget` / `monthly_dollar_budget`. Absent = unchanged, explicit `null` = clear. |
| `GET` | `/analytics` | `?days=1..365` (default 30): totals, per-model/provider/purpose breakdown, latency percentiles, acceptance/push-back rates, monthly budget. |
| `POST` | `/settings/test-connection` | Probe the active `version_control` and `llm` keys. |
| `GET` | `/keys/version-control` | List GitHub/GitLab tokens (masked, `is_active`). |
| `POST` | `/keys/version-control` | `{provider, token, base_url?, label?}` → 201. |
| `PATCH` | `/keys/version-control/{id}` | Replace token, base URL or label. |
| `DELETE` | `/keys/version-control/{id}` | Delete the key (clears the active pointer). |
| `POST` | `/keys/version-control/{id}/test` | Probe that token against its host. |
| `GET` | `/keys/llm` | List model-provider keys (masked, `is_active`). |
| `POST` | `/keys/llm` | `{provider, api_key?, base_url?, default_model?, label?}` → 201. |
| `PATCH` | `/keys/llm/{id}` | Replace secret, base URL, default model or label. |
| `DELETE` | `/keys/llm/{id}` | Delete the key. |
| `POST` | `/keys/llm/{id}/test` | Probe that provider. |
| `GET` | `/models` | Model options, `preferred`, and the skill manifest. |
| `GET` | `/skills` | Foundations discovered on disk, with file counts. |
| `POST` | `/skills/files` | Upload one `.md`/`.txt` into the default foundation. |
| `POST` | `/skills/foundings` | Create a foundation from a folder (`files[]`) or a `.zip` (`archive`). |
| `DELETE` | `/skills/foundations/{id}` | Remove an uploaded foundation (the default is protected). |
| `GET` | `/reviews` | Review history, newest first. |
| `POST` | `/reviews` | Accept a review (`202`) and start the ingest job. |
| `GET` | `/reviews/{id}` | Review with threads, messages, verdict and confidence. |
| `GET` | `/reviews/{id}/events` | Server-Sent Events stream of ingest progress. |
| `POST` | `/reviews/{id}/discuss` | Bulk discussion, one model call per thread. |
| `POST` | `/reviews/{id}/sync` | Fetch the PR's comments and append unseen replies/threads. |
| `POST` | `/reviews/{id}/rounds/{round_id}/decision` | Queue a round (`publish`), close it (`resolve`) or reopen it (`draft`). |
| `POST` | `/reviews/{id}/apply` | Publish pending work: one review for new findings, one reply per queued round. |
| `GET` | `/watches` | Watched pull requests with their last check and last error. |
| `POST` | `/watches` | `{review_id}` → `201`, or `200` with the existing watch for that PR. Copies the review's model and foundation. |
| `PATCH` | `/watches/{id}` | `{enabled}` — pause or resume. |
| `DELETE` | `/watches/{id}` | Stop watching (`204`). |
| `POST` | `/watches/tick` | **Public, secret-authenticated** (`Authorization: Bearer` or `X-Watch-Secret`): check every watch once. `503` when `WATCH_TICK_SECRET` is unset, `401` on a wrong secret. |

### `POST /api/reviews` (202)

```json
{ "pr_url": "https://github.com/owner/repo/pull/123",
  "model": "ollama-cloud:gpt-oss:20b",
  "skill_foundation": "frontend-guidelines" }
```

Model ids are `<provider>:<name>` with provider `claude`, `ollama-cloud` (the default for
Ollama) or `ollama-local`. The name passes through verbatim, so tags containing `:` work
(`ollama-cloud:gpt-oss:20b`). The legacy `ollama:<tag>` form is still accepted and resolves to
cloud — but local models must be addressed as `ollama-local:<tag>`. The prefix is stored in
`model_used`, so a review keeps calling the transport it was created with.

`POST /api/reviews` returns `202` with the new id; the findings arrive through the event stream
and then `GET /api/reviews/{id}`.

### `GET /api/reviews/{id}/events`

`text/event-stream`, events `progress` / `done` / `failed`. History is replayed first, so a late
or reconnecting client still sees the earlier steps; a `: ping` keeps the connection alive.

```json
{ "seq": 6, "ts": "2026-11-07T08:01:12.512Z", "stage": "model", "label": "Asking gemma4:31b",
  "detail": "Waiting for the model to return findings…", "level": "info", "progress": 55 }
```

### `POST /api/reviews/{id}/discuss`

```json
{ "threads": [ { "thread_id": 21, "message": "Same root cause as #1?" } ] }
```

`200` returns the updated review plus per-thread results including resolved references:

```json
{ "thread_id": 21, "ok": true, "error": null, "references": [1] }
```

### `POST /api/reviews/{id}/sync`

No body. `200` → `{review, new_threads, new_rounds, warnings[]}`. A new reply opens a round
(`thread_status=needs_response`); a new top-level comment creates a `GITHUB_EXISTING` thread. The
call is idempotent: the second run reports `0 / 0`. GitLab reviews get an explanatory warning and
make no requests.

Identity is the GitHub id, never the author: a comment is this review's own only when it belongs to
the review it published (`pull_request_review_id` from `github_review_url`), so the operator can reply
from the same GitHub account the token uses. Sync also repairs AI threads whose
`github_root_comment_id` was never recorded, matching the text the tool posted, so a reply to a
finding still threads correctly.

### `POST /api/reviews/{id}/rounds/{round_id}/decision`

```json
{ "decision": "accept", "summary": null }
{ "decision": "push_back", "summary": null }
```

`accept` moves the round to `pending_apply` so the next apply publishes it. With no `summary` it
first runs one model pass over the thread and the round and stores the rewritten GitHub comment
(falling back to the copilot's last message, reported in `warnings`); with a `summary` it stores that
text verbatim and does not call the model. On the first round of an AI finding it also clears an
earlier withdrawal. `push_back` marks the round `resolved_no_reply` and the thread `resolved`, and
withdraws the finding when it is that first round, so nothing is posted for it. `publish` and
`resolve` are accepted as aliases of the two. `200` → `{review, warnings[]}`; `404` when the round is
not part of the review, `409` when it is already published.

### `POST /api/reviews/{id}/apply`

```json
{ "event": "REQUEST_CHANGES", "thread_ids": [21, 22] }
```

No body field: the review is created with inline comments only, and no summary body. `200` →
`{review, github_review_url, comments_posted, replies_posted, summarised, dropped[], warnings[]}`.
`400` when nothing is accepted yet and the event is not `APPROVE`, or a thread id is foreign, `409`
once everything is already on GitHub, `422` when every accepted finding no longer matches the diff,
`502` when GitHub rejects the call.

`{ "event": "APPROVE" }` with nothing accepted is the exception: it posts an approval with an empty
`comments` list (`comments_posted: 0`), which is what the GitHub UI's approve button sends.

Accepted AI findings are published as one review; their comment ids are read back and stored so
later replies can be threaded. Every `pending_apply` round is then posted with
`POST /pulls/{n}/comments/{root_id}/replies` and its returned id is stored. A comment body is the text
the reviewer accepted for that round — generated on Accept, or the wording they saved — so an apply
never rewrites an approved comment; only a legacy round with no accepted text goes through the
pre-publish summariser and collation fallback. Pushed-back threads are excluded and reported in
`dropped[]`.

## Data model

Twelve tables, created by fourteen Alembic revisions (`0001` … `0014_linked_review_watches`;
`0010` was never used — the numbering skips it).

```
users
  email (unique, lower-cased), password_hash (pbkdf2_sha256$iterations$salt$hash),
  created_at, updated_at

sessions                    FK user_id → users.id  (cascade delete)
  token_hash (sha256 of the cookie value, unique), expires_at, created_at

version_control_keys        FK user_id → users.id  (cascade delete)
  provider (github | gitlab), token (`enc:v1:` Fernet ciphertext), base_url (null = provider
  default), label, created_at, updated_at

llm_keys                    FK user_id → users.id  (cascade delete)
  provider (claude | openai | ollama_cloud | ollama_local),
  api_key (encrypted; null for ollama_local), base_url, default_model, label, created_at, updated_at

settings (one row per user, unique user_id)
  user_id               → users.id                (on delete cascade)
  version_control_key_id → version_control_keys.id  (on delete set null)
  llm_key_id            → llm_keys.id               (on delete set null)
  monthly_token_budget  (bigint, null = uncapped),
  monthly_dollar_budget (float, null = uncapped),
  updated_at

code_reviews                FK user_id → users.id  (cascade delete)
  pr_url, vcs (github | gitlab), pr_title, pr_number, repo_full_name, commit_id, model_used,
  skill_foundation,
  status (running | draft | in_discussion | applied | failed),
  verdict (APPROVE | REQUEST_CHANGES | COMMENT),
  suggested_verdict, confidence_percentage, suggested_verdict_note,
  error, notes, github_review_url,
  parent_review_id (the review this one continues, null = first of its line),
  watch_id (the watch that started it), trigger (watch | null = started by hand),
  created_at, updated_at

review_threads          FK review_id → code_reviews.id  (cascade delete)
  file_path, line_number, diff_hunk, side, summary, dropped, created_at,
  origin (AI_GENERATED | GITHUB_EXISTING), github_root_comment_id, original_author,
  current_round, thread_status (active | needs_response | applied | resolved)

thread_rounds           FK thread_id → review_threads.id  (cascade delete)
  round_number, inbound_github_comment_id, inbound_author, inbound_body, final_summary,
  status (drafting | pending_apply | published | resolved_no_reply),
  published_github_comment_id, created_at, updated_at

thread_messages         FK thread_id → review_threads.id  (cascade delete)
  role (assistant | user | system), content, round_number, is_external, author,
  github_comment_id, created_at

review_events           FK review_id → code_reviews.id  (cascade delete)
  seq (unique per review), ts, stage, label, detail, level, progress, data, terminal

llm_calls               FK review_id → code_reviews.id  (cascade delete, nullable)
                        FK thread_id → review_threads.id (on delete set null, nullable)
  purpose (ingest | discuss | verdict | summarise), provider, model,
  prompt_tokens, completion_tokens, total_tokens, estimated_cost_usd,
  latency_ms, ok, error_class, created_at

review_watches          FK user_id → users.id              (cascade delete)
                        FK last_review_id → code_reviews.id (on delete set null, nullable)
  pr_url (unique per user with user_id), vcs (github | gitlab), repo_full_name, pr_number,
  skill_foundation, model_used,
  last_seen_commit_id (the delta base; null = adopt the head on the next check),
  enabled, last_checked_at, last_error, created_at, updated_at
```

`llm_calls` holds **counts, not text**: no prompt, system prompt, diff or completion is stored, so
the ledger cannot leak what was reviewed. `provider` is the model-id prefix (`claude`, `openai`,
`ollama-cloud`, `ollama-local`) and `model` is the bare name, so a row joins a review's
`model_used` on `provider:model`. Token columns are `NULL`, never `0`, when the provider or model
does not report usage. Ownership is reached through `review_id → code_reviews.user_id`, which is why
there is no duplicate `user_id` column. Indexes: `(review_id, created_at)` for the per-review usage
line and `(created_at, provider, model, purpose)` for the analytics window.

`github_comment_id` is the dedupe key: every comment this review has seen or posted is remembered
there (and on the thread's root id and the round's inbound/published ids), which is what makes a sync
idempotent. Migration `0009` backfills one round per pre-existing thread instead of dropping
anything.

`settings` holds no secrets: it points at the active key of each family, and deleting a key clears
the pointer rather than cascading. Foreign keys are `ON DELETE CASCADE` for reviews, so deleting a
review removes its threads and their messages on both engines (SQLite needs
`PRAGMA foreign_keys=ON`, set on every connection). Rows that predate accounts are attached to a
disabled `legacy@localhost` account by migration `0008` — it cannot sign in and holds the data
until an operator reconfigures it.

## How a review is produced

| Step | Module | What happens |
|---|---|---|
| 1 | `services/github_service.py` | `parse_pr_url` → owner/repo/number; fetch metadata, then the diff with `Accept: application/vnd.github.v3.diff`. |
| 2 | `services/diff_parser.py` | Split into `FileDiff`/`Hunk`/`Line`, number the RIGHT side, mark binaries, skip lockfiles (`package-lock.json`, `Gemfile.lock`, …), generated assets and vendored dirs. |
| 3 | `services/skill_loader.py` | Recursively read the skill library; always include `SKILL.md`, then rank references by token overlap with changed paths plus core terms (`rubric`, `verification`, `output`, …) until the budget is spent. |
| 4 | `services/prompts.py` | System prompt = skills + output contract. User prompt = PR identity and a numbered diff whose left column is the only legal anchor set. |
| 5 | `services/llm_service.py` | Claude Messages API, Ollama Cloud (`https://ollama.com/api`, bearer key) or a local daemon, resolved from the model-id prefix (`format: json` only for review generation; discussions are prose). Returns an `LLMResult` (text + reported tokens + latency) and records the call through `services/ledger.py`. |
| 6 | `services/review_pipeline.py` | Runs as a background job, publishing SSE progress at each stage. Imports existing PR comments (grouped by root, as `GITHUB_EXISTING` threads), parses `{verdict, confidence, findings}`, anchors each finding to a real line, rebuilds the hunk, persists threads with their first round, records warnings. A diff over `DIFF_MAX_CHARS` is split by `services/review_units.py` into parts of whole files, reviewed with bounded concurrency, then merged: anchored, deduped per line, capped by severity, and given one verdict pass over the result. |
| 7 | `services/discussion.py` | Append user messages, resolve `#N` references, `asyncio.gather` one call per thread, append replies, flip status to `in_discussion` if anything succeeded. |
| 8 | `services/summarise.py` | Pre-publish pass: one comment per thread, or withdraw it when the finding was conceded. Best-effort. |
| 9 | `services/apply_service.py` | Prune pushed-back threads, re-validate anchors against the live diff, POST the review with its inline comments only, backfill its comment ids, then POST one reply per accepted round. |
| 10 | `services/thread_sync.py` | Group PR comments into threads, import them at ingest, and append unseen inbound comments as new rounds on sync. |

Budgets and truncation are explicit: when the diff or skill library does not fit, the model is
told what was cut and the review records a warning for the operator. A diff too large for one call
is reviewed in parts rather than cut — see **Large change requests** below.

Steps 5–9 all funnel through `llm_service.generate`, which is the one place a provider call is made
and the one place an `llm_calls` row is written — so spend by purpose, per model, and the latency
percentiles on `/analytics` describe exactly the calls the pipeline made.

### Large change requests

A diff that fits `DIFF_MAX_CHARS` is one model call and its own verdict, exactly as it always was.
Past that ceiling the change is **not** truncated:

1. `services/review_units.py` packs the reviewable files, in diff order, into parts of at most
   `REVIEW_UNIT_CHARS`. A file is never split; one file larger than a part gets a part of its own.
2. One call per part, at most `LLM_REVIEW_CONCURRENCY` in flight. Each part is told `part i of n`
   and lists the only files it may report on, and each one writes its own `llm_calls` row with
   `purpose="ingest"`.
3. The findings are anchored against the **full** parsed diff, deduped per line (the longest body
   wins), then capped at `REVIEW_MAX_FINDINGS`, highest severity first.
4. One extra call — `purpose="verdict"` — decides `suggested_verdict` over the merged findings,
   because no single part saw the whole change. It uses the same `{verdict, confidence, rationale}`
   contract as the post-discussion pass.

Progress shows one row per finished part ("Reviewed 2 file(s) (part 3 of 8)"), so a slow part is
visible while the others are already done. If a part fails, the review still lands as `draft` with
the findings that did arrive and a note naming the part whose files were not covered; if every part
fails the review is `failed`, as before. A 130 876-character / 16-file change costs 8 ingest calls
plus 1 verdict call and stores every finding anchored.

## Project structure

```
code-review-master/
├── backend/
│   ├── app/
│   │   ├── api/routes/          settings.py · keys.py · reviews.py · watches.py · models.py
│   │   │                        skills.py · analytics.py
│   │   ├── core/                config.py (settings, paths) · crypto.py (credential encryption)
│   │   ├── db/                  base.py · session.py (engine, get_db) · init_db.py (migrations)
│   │   │                        types.py (EncryptedText) · encryption.py (backfill, rotation)
│   │   ├── models/              keys.py (version control + LLM) · settings.py · review.py
│   │   │                        llm_call.py (call ledger) · watch.py (watched PRs)
│   │   ├── schemas/             keys.py · settings.py · review.py · watch.py · skills.py
│   │   │                        analytics.py
│   │   ├── services/            vcs.py · github_service · gitlab_service · keys_service
│   │   │                        diff_parser · skill_loader · prompts · llm_service
│   │                        review_pipeline · thread_sync · discussion · summarise
│   │                        apply_service · references · skills_service · progress · secrets
│   │   │                        settings_service · pull_request · ledger · analytics
│   │   │                        review_units · watch_service · verdict
│   │   └── main.py              app factory, CORS, router registration, lifespan
│   ├── alembic/                 0001_initial_schema · 0002_review_notes · 0003_ollama_cloud
│   │                            0004_skill_foundation · 0005_review_intelligence
│   │                            0006_provider_keys · 0007_verdict_note
│   │                            0008_users_and_ownership · 0009_thread_rounds
│   │                            0011_encrypt_credentials · 0012_review_events
│   │                            0013_llm_calls (no 0010)
│   ├── tests/                   221 tests across 21 test modules (SQLite, via real migrations)
│   ├── scripts/                 migrate_sqlite_to_postgres.py (rake-style DB copy)
│   │                            generate_encryption_key.py · rotate_credentials_key.py
│   ├── alembic.ini  pytest.ini  requirements.txt  main.py  .env.example
├── frontend/
│   ├── src/
│   │   ├── components/          Navbar · NewReviewPanel · SplitPane · CodeSnippetBox
│   │   │                        CommentBox · RoundPanel · ThreadFilterBar · DiffViewer
│   │   │                        ReviewHeader · StickyActionBar · WarningsBanner
│   │   │                        KeyManager · SetupGate · IngestProgress · FoundationUpload · ui/*
│   │   ├── pages/               DashboardPage · ReviewDetailPage · SettingsPage · SetupPage
│   │   │                        SkillsPage · AnalyticsPage
│   │   ├── context/             SettingsContext (one settings fetch, needs_setup, refresh)
│   │   ├── services/api.ts      typed fetch wrapper (ApiError carries status + detail)
│   │   ├── hooks/               useReviewDrafts
│   │   ├── types/               interfaces mirroring the Pydantic schemas
│   │   └── lib/utils.ts         cn, relativeTime, compactNumber, estimatedCost, formatDuration
│   ├── tailwind.config.js  vite.config.ts  tsconfig.json  package.json
├── code-review/                 the injected skill library (SKILL.md + references/)
├── docs/plans/                  phase 1–16 implementation plans with Mermaid diagrams
└── README.md
```

## Development

```bash
# backend
cd backend && source .venv/bin/activate
pytest                      # 221 tests, ~5s
alembic revision -m "msg"   # new migration (hand-edit it, keep it dialect-agnostic)

# frontend
cd frontend
npm run dev
npm run typecheck           # tsc --noEmit
npm run build               # tsc -b && vite build
```

The backend suite runs against a temporary SQLite file created by the **real** Alembic
migration (independent of the PostgreSQL database you use day to day), with GitHub and the model
stubbed at the service boundary (`app.services.*`), so the HTTP contract, anchoring and
persistence are exercised end to end without network calls.

Coverage map:

| File | Focus |
|---|---|
| `test_settings_api.py` | masking, reveal, patch semantics, URL validation, connection-test failures |
| `test_diff_parser.py` | numbering, deleted lines, binary/lockfile skips, anchoring, snippet rebuilding |
| `test_skill_loader.py` | discovery, entry-file priority, budget, relevance ranking |
| `test_llm_parsing.py` | JSON extraction (fences/prose/wrapped), model-id grammar |
| `test_review_pipeline.py` | ingest 201/400/404/422/502, dropped findings, model catalog |
| `test_discussion.py` | batch contract, concurrency, partial failure, status transitions |
| `test_apply.py` | payload shape, subset export, stale anchors, 422 retry, 409, failure isolation |
| `test_ollama_transport.py` | cloud vs local catalogue, missing-key guard, legacy id → cloud |
| `test_skills_api.py` | single-file and folder/zip foundation uploads, traversal and cap guards, delete rules |
| `test_progress.py` | 202 + SSE stages, replay for late subscribers, failure event, orphan reconciliation |
| `test_references.py` | `#N` resolution, prompt block, references in the discuss response |
| `test_db_migration_script.py` | SQLite URL resolution, UTC re-attachment, refusal of a SQLite target or identical endpoints |

### Adding review standards

Drop a `.md` or `.txt` file anywhere under `code-review/` (or `SKILLS_DIR`). It is discovered on
the next review; ranking prefers files whose names/paths match the changed file extensions and
directories, so name domain files after what they govern (`reference/payments.md`). Raise
`SKILLS_MAX_CHARS` if you want more of the library in the prompt.

### Adding a model provider

1. Extend `parse_model_id` in `llm_service.py` with the new provider prefix.
2. Implement the call in `generate()` and return raw text.
3. Add the provider's models in `api/routes/models.py` so the dashboard can select them.
4. For structured review output, the provider must be able to return JSON — either natively or
   through the prompt contract that `prompts.build_system_prompt` already enforces.

## Design notes and limitations

- **Local-first by design.** Provider credentials are encrypted at rest with a key from the
  environment (`CREDENTIALS_ENCRYPTION_KEY`), so database copies are inert without it — but the key
  sits on the machine that runs the app. That is appropriate for a single-operator tool, not a
  shared deployment; move the key to a secret store before exposing the API to a network.
- **`applied` is terminal for a local review.** GitHub reviews are immutable, so a second apply
  returns `409` instead of silently posting a duplicate. Start a new review to re-review.
- **A crashed ingest fails the review.** Any exception the pipeline does not expect is logged with
  its traceback, recorded as `failed` with a one-line cause, and ends the progress stream with a
  terminal `error` event — a review never sits at a percentage forever.
- **Anchors can go stale.** A review targets the HEAD SHA recorded at ingest. If the branch
  moves, the apply step drops the anchors that no longer exist and says so rather than failing
  the whole publish.
- **Very large files are still cut.** A diff past `DIFF_MAX_CHARS` is reviewed in parts, so the
  60 000-character mark no longer silently drops the rest of the change. The remaining exception is
  a single file whose first hunk alone overflows a part: it is cut mid-hunk, and the review records
  that it was.
- **Parts do not see each other.** Each part reads only its own files, so a defect that only makes
  sense across two files can be missed. The verdict pass sees every finding but never the code.
- **No streaming.** A slow local model means a spinner with an elapsed-seconds counter.
- **A watch checks on a timer, not on a push.** Locally that is a ten-minute loop, on Vercel a cron
  at the same period, so a new commit is reviewed up to ten minutes late. There is no webhook.
- **A delta review is one review, not a conversation continued.** It links to the review it
  continues, but threads are not copied forward: the earlier review's discussion stays where it was
  written, and a comment the delta cannot anchor to is dropped at apply with a warning.
- **Cost is an estimate, never a bill.** Rates live in `app/core/pricing.py` (USD per 1M tokens,
  prefix-matched); a model that is not listed reports tokens and no dollars. Nothing is reconciled
  against a provider invoice, and the ledger stores no prompt text, so the numbers describe calls
  but cannot reconstruct them.
- **Single-user.** There is no authentication on the API; it binds to localhost and is meant to.
- **Discussions see the anchored hunk, not the repository.** The model can compare the change
  against the diff context and the skill rules; it cannot browse the codebase.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Cannot reach the API. Is the backend running on :8000?` | Start uvicorn, or check the Vite proxy target. |
| `No GitHub token configured. Add one in Settings.` | Save a GitHub key (or switch the active key to GitLab) first; the pipeline refuses to guess. |
| `No GitLab token configured. Add one in Settings.` | The URL is a GitLab merge request but no GitLab key exists. |
| `GitLab rejected the token (401)` | Token is wrong/expired, or the wrong key is active. |
| `GitHub rejected the token (401)` | Token expired or missing scope (`repo`, or PR read/write for fine-grained). |
| `GitHub rate limit reached` | Unauthenticated/over-quota traffic; wait or use a token with quota left. |
| `Could not reach Ollama at http://localhost:11434` | Local mode with no daemon running (`ollama serve`) or a wrong base URL. |
| `Ollama Cloud rejected the API key (HTTP 401)` | The key is wrong or revoked — create a new one at ollama.com/settings/keys. |
| `No Ollama Cloud API key configured` | Cloud is the default mode; add a key in Settings, or switch the card to Local daemon. |
| `Watch ticks are not configured` (`503`) | Set `WATCH_TICK_SECRET` (and `CRON_SECRET` to the same value on Vercel) so the cron tick can authenticate. |
| A watch shows “Last check failed” | The stored first line names the cause — usually a force-push (`compare` cannot reach the old commit) or an expired token. The delta is retried on the next tick once the cause is fixed. |
| `Ollama does not have the model 'x'` | Cloud: pick a model id from `GET https://ollama.com/api/tags`. Local: `ollama pull x`. |
| Dashboard bounces to `/setup` | `needs_setup` is true: one version-control key **and** one model key must be active. |
| `A foundation named 'x' already exists.` | `409` by design — delete it on the Skills page or pick another name. |
| `No .md or .txt files found in the upload.` | The folder/zip contained no markdown; only `.md`/`.txt` are stored. |
| `unknown skill foundation` on start | The folder was deleted after the page loaded; refresh the dashboard. |
| Review stuck on `Running` | The ingest job died with the process; a restart marks it `failed` with the reason. |
| SSE stream reconnects | Expected: the browser retries and the server replays history from the start of the job. |
| `Model returned no parsable JSON` | The model ignored the contract; retry, or use a model that follows JSON instructions. The failed review keeps `error` and `review_id`. |
| `GitHub rejected the inline comments … posted the review summary only` | A comment anchor was rejected; the verdict and summary still landed, warnings list the rest. |
| `This review was already applied to GitHub.` | `409` by design — open a new review instead. |
| Everything masked as `••••••••` | By design; add a replacement key, or `GET /api/keys/llm?reveal=true` to read a value. |
| `127.0.0.1:5173` refused but `localhost:5173` works | Vite bound IPv6 `::1`; use `npm run dev -- --host 127.0.0.1`. |

## Documentation

- `docs/plans/phase_1_plan.md` … `phase_21_plan.md` — objective, Mermaid design diagrams, API
  contracts, file map, verification criteria for each phase.
- `INITIATIVES.md` — ranked backlog of the next features, each with evidence, design sketch,
  touch points and verification, plus what was deliberately deferred.
- `CHANGELOG.md` — what shipped in each phase, grouped by Added / Changed / Removed / Fixed.
- `AGENTS.md` — contributor/agent conventions: the plan-first rule, architecture, database rules,
  testing gates and gotchas.
- `backend/rules/`, `frontend/rules/` — folder-scoped rules that refine `AGENTS.md` for that area.
- `MASTER_PROMPT.md` — the original product/architecture brief this implementation follows.
- `/docs` on the running backend — generated OpenAPI explorer.