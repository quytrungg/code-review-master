# Changelog

All notable changes to the AI Code Review Assistant, newest first. Each entry maps to the plan in
`docs/plans/` that specified it, so the "why" lives there and this file stays a record of what
shipped.

Conventions: **Added** / **Changed** / **Removed** / **Fixed** / **Security**. Migration numbers
refer to `backend/alembic/versions/`.

---

## Phase 24 — Ollama Cloud is metered, so its calls are no longer estimated at zero — 2026-11-10

Plan: `docs/plans/phase_24_plan.md`. No schema change; `alembic_version` stays at head. The stored
costs were repaired by `scripts/backfill_llm_costs.py --apply` (38 rows, see the plan).

### Fixed

- **Every Ollama Cloud call was estimated at `$0.00`.** `FREE_PROVIDERS` listed `ollama-cloud`, a
  policy written when the cloud had no per-token price; Ollama moved to per-token billing on
  2026-08-31. `ollama-cloud` is now priced like any other hosted provider and only `ollama-local`
  (your own hardware) reports a genuine zero.
- **Costs on the analytics page and the review header** for this account move from `~$0.00` to
  `~$0.33` for the 800,844 tokens in the ledger, and the monthly dollar budget now uses that figure.

### Added

- **The published Ollama Cloud catalogue in `app/core/pricing.py`** — 21 models, USD per 1M tokens,
  input/output, standard rates, checked against `https://ollama.com/pricing` on 2026-11-10.
  `clef` is omitted: it publishes no output rate, which this table cannot express.
- **`scripts/backfill_llm_costs.py`** — recomputes `estimated_cost_usd` from each row's own tokens.
  Dry run by default; `--apply` writes; idempotent; rows whose model has no published price, and
  failed calls with no tokens, are left untouched.

### Changed

- **`tests/test_llm_usage.py`**: the old test asserted that `ollama-cloud` costs nothing; it now
  asserts the local daemon is free, a cloud model is priced by prefix, and an unpriced cloud model is
  `None` rather than zero.
- **README / `backend/rules/conventions.md`** describe the price source, the standard-tier caveat
  and the repair script.

---

## Phase 23 — Approve a pull request with nothing to publish — 2026-11-10

Plan: `docs/plans/phase_23_plan.md`. No schema change.

### Changed

- **`POST /api/reviews/{id}/apply`** accepts `{"event": "APPROVE"}` on a review where nothing is
  accepted. Instead of the `400` "nothing is accepted yet", it publishes an approval with
  `comments: []` — the review the GitHub UI's approve button creates — and records the verdict and
  review URL as usual. `COMMENT` and `REQUEST_CHANGES` still need at least one accepted finding, and
  accepted findings that pruning removes entirely are still a `422`.
- **Action bar**: with nothing pending and `APPROVE` selected, the apply button reads **Approve on
  GitHub** instead of sitting disabled at "Everything applied". A second apply with nothing pending
  is the existing `409`.
- **GitLab**: an approval with no comments posts no discussions and calls the approval endpoint;
  a refusal is the usual warning, not a failure.

---

## Phase 22 — LLM call ledger, cost estimation and review-quality analytics — 2026-11-09

Plan: `docs/plans/phase_22_plan.md` (requested as "phase 10", which was already the provider
credentials plan; numbered 22 per `AGENTS.md` §1).

### Added

- **`llm_calls` (Alembic `0013`).** One row per provider call: purpose, provider, model, prompt and
  completion tokens, `total_tokens`, estimated cost, latency, `ok` and `error_class`. Counts only —
  no prompt, system prompt, diff, completion or reviewer message is stored. Indexes
  `(review_id, created_at)` and `(created_at, provider, model, purpose)`.
- **`LLMResult`.** `llm_service.generate` returns the dataclass (text, tokens, latency) instead of a
  bare string, and records the call whether it succeeded or failed. Token extraction is a pure
  function per provider: `claude_usage` (response body or `message_start`/`message_delta` events),
  `openai_usage` (the terminal `usage` object), `ollama_usage` (`prompt_eval_count`/`eval_count`,
  with missing or `0` counters stored as `NULL`).
- **`app/core/pricing.py`.** USD per 1M tokens by model prefix, longest prefix first so
  `gpt-4o-mini` beats `gpt-4o`. An unlisted model costs `NULL`; Ollama costs `0.0`.
- **`services/ledger.py`.** The insert runs in its own `SessionLocal` and every failure is a logged
  warning, so telemetry can never fail or roll back a review.
- **`GET /api/analytics?days=30`.** Totals, per-provider/per-model/per-purpose breakdowns, median
  and p95 latency, acceptance and push-back rates per model, and current-month budget utilisation.
- **`settings.monthly_token_budget` / `monthly_dollar_budget`.** Soft caps: amber from 80%, red from
  100%, nothing blocked.
- **`/analytics`** (nav tab): KPI cards, model comparison table, purpose breakdown, budget manager.
  **Dashboard**: 30-day activity bar and budget banner. **Review header**: `4 calls · 61.1k tokens ·
  ~$0.06 · 2m 14s total`, refreshed after each action.

### Changed

- `review_pipeline`, `discussion`, `verdict` and `summarise` pass `purpose`, `review_id` (and
  `thread_id` where one exists) into `generate`, so spend is attributable per activity.
- `CodeReviewSummary.usage` (`calls`, tokens, estimated cost, total latency) is filled on every
  detail response; the list endpoint stays a single query.
- `PUT /api/settings` accepts the two caps: absent keeps the value, explicit `null` clears it.

### Verified

- `pytest -q` → 221 passed (191 before, 30 new across `test_llm_usage.py` and
  `test_analytics_api.py`); `npm run build` green.
- `0013` round-trips `upgrade` → `downgrade -1` → `upgrade` on a scratch SQLite file; both indexes
  and both foreign keys (`CASCADE`, `SET NULL`) are present afterwards.
- Live run on a scratch database with a stubbed provider (two findings, one discussion, one accept,
  one apply): `POST /api/reviews` `202` → `draft` with `usage = {calls: 1, total_tokens: 9880,
  estimated_cost_usd: 0.039}`; `POST /discuss` `200`, `POST /apply` `200`;
  `GET /api/analytics?days=30` `200` reporting 3 calls, 16 260 tokens, `$0.0627` total
  (ingest `$0.0390`, discuss `$0.0147`, verdict `$0.0090`), median 2 000 ms / p95 2 250 ms,
  acceptance 50.0% (1 of 2 findings) and push-back 50.0%; the header line read
  `3 calls · 16.3k tokens · ~$0.06 · 6s total`.
- With `ledger.SessionLocal` forced to raise, a full ingest still finished `draft` with both
  threads and logged one warning.

---

## Phase 15 — Vercel + Supabase deployment, Python 3.12 and a database-backed progress bus — 2026-11-08

Plan: `docs/plans/phase_15_plan.md`.

### Added

- **`review_events` (Alembic `0012`).** Progress stages are rows now, not process memory, so the
  ingest job and the browser's SSE stream can be served by different instances and a late tab
  replays every stage. Numbered `0012` rather than the `0010` slot 0011 had reserved: every database
  was already stamped `0011`, so a revision inserted behind head would never run.
- **Vercel deployment.** `vercel.json` (Services: `web` + `api`, top-level `/api/*` routing,
  `maxDuration=300`, `includeFiles: code-review/**`), `.vercelignore`, and
  `backend/.python-version` pinned to 3.12.
- **Serverless mode** (`SERVERLESS=true`): `NullPool` with `prepare_threshold=None` for Supabase's
  transaction pooler, no migrations or orphan sweep at startup, and stale `running` reviews failed
  on read after ten minutes.
- **Feature guards**: `GET /api/skills` reports `uploads_enabled`, `SIGNUP_ENABLED=false` refuses
  sign-up, `ollama-local:` is rejected (`422`) and hidden from `/api/models`.

### Changed

- **Python 3.12 is the tested runtime** (CPython 3.12.12): the Docker base image moved from
  `python:3.11-slim` to `python:3.12-slim`; Vercel offers 3.12/3.13/3.14 only.
- **Skill files are read-only on a deployment.** Upload, create and delete return `403` with a
  sentence naming the alternative (add markdown to `code-review/` and redeploy), and the Skills page
  hides the write controls. Runtime uploads return with object storage
  (`docs/plans/phase_21_plan.md`).
- **Ingest is scheduled as a background task in serverless mode**, so the function keeps running
  after the `202` and the review finishes with no SSE client attached.
- `fail_orphaned_reviews()` stays the startup sweep for local and container runs; serverless reads
  use `mark_stale_running_reviews()` instead, because another instance may own the row.
- **The container keeps its skill library in the volume.** The image's `code-review/` is a seed at
  `/opt/code-review`; `docker-entrypoint.sh` copies it to `/data/code-review` when the volume is
  empty, and `SKILLS_DIR` points there. Before this, a single-file upload inside the container
  failed with `500 PermissionError` (the bundled directory was root-owned and outside `/data`), and
  any write would have disappeared with the container.

### Verified

- `pytest -q`: **191 passed** on CPython 3.11.14 and on **3.12.12** · `npm run build` green.
- Alembic on scratch SQLite and scratch PostgreSQL: a database stamped `0011` gains
  `review_events` on `upgrade head`, `downgrade -1` removes it, `upgrade` restores it.
- Serverless engine selects `NullPool` (local still `QueuePool`); with `SERVERLESS=true` an empty
  database stays empty at startup (`alembic_version` never created) and `/api/health` returns 200.
- `docker build` on `python:3.12-slim` runs `python 3.12.16`, migrates to `0012`, seeds
  `/data/code-review` (26 files), accepts a sign-up and a skill upload (`201`), keeps that upload
  after `docker restart`, and stores a duplicate as `container-rule-2.md`.

---

## Phase 20 — Inline comments only, and a round that starts undecided — 2026-11-08

Plan: `docs/plans/phase_20_plan.md`.

### Removed

- **The fixed review body.** Every apply used to create its GitHub review with
  `Code review completed with {n} inline findings, discussed and verified by human - By Code Review
  Master`, and a 422 fell back to posting that body alone. `POST /pulls/{n}/reviews` now carries
  `commit_id`, `event` and `comments` — nothing else. `MANDATED_BODY`/`mandated_body()` are gone from
  `vcs.py`, `apply_service.py` and the frontend, and GitLab no longer posts a summary note.
- **The summary-only fallback.** A rejected review is now a `502` and a fully pruned one a `422`;
  neither posts anything. An empty review was noise, and the warnings it carried were easy to miss.

### Changed

- **A new AI finding is undecided (`drafting`), not accepted.** `apply` selects findings whose round
  is `pending_apply`, so nothing reaches GitHub until the reviewer clicks **Accept** — which is what
  makes the first round show its decision, instead of being published as a side effect of applying
  somebody else's thread.
- The action bar's "pending" count no longer counts undecided findings: it counts accepted, unposted
  rounds only, so **Apply** stays disabled until there is something accepted.
- An apply with nothing accepted is a `400` ("Nothing is accepted yet…") rather than posting.

### Verified

- `pytest -q`: **185 passed** · `npm run build` green.
- `POST /pulls/{n}/reviews` captured in `tests/test_apply.py` has no `body` key; a rejected review
  makes exactly one call and leaves the review `draft`.

---

## Phase 19 — Accept writes the GitHub comment, and you can edit it — 2026-11-08

Plan: `docs/plans/phase_19_plan.md`.

### Fixed

- **A reply is no longer the chat message pasted into GitHub.** `decide_round(accept)` used to store
  `_last_assistant_text(...)`, so the reply for thread 42 was message 70 verbatim (727 characters of
  conversation), and the summariser never saw reply rounds at all. Accept now runs one round-scoped
  model pass and stores a self-contained GitHub comment.

### Changed

- **`summarise.summarise_round`** with `ROUND_SUMMARY_CONTRACT`: input is the thread anchor, the diff
  hunk, the transcript up to that round and the round's inbound comment; output is one comment —
  severity prefix and agreed fix for a first-round finding, a direct answer for a reply.
- `POST …/rounds/{id}/decision`: `accept` without `summary` generates the text; `accept` with
  `summary` stores the reviewer's wording verbatim and makes no model call; a failed or malformed
  pass keeps the copilot's message and returns a warning. The response gained `warnings[]` and the
  route is now `async`.
- **Apply posts the accepted text unchanged.** Initial findings are split: threads with an accepted
  `final_summary` are published as-is, only the rest still go through the pre-publish summariser and
  collation fallback — so an approved (or edited) comment can never be rewritten at apply time.
- UI: an accepted round shows an editable "This is what will be posted" box with **Save changes**;
  decision warnings surface in the notice line.

### Verified

- `pytest -q`: **184 passed** (180 + 4) · `npm run build` green.
- Live check on review 12's real threads (summaries generated, nothing written): thread 41 round 2 →
  "Closing this thread as deferred, not fixed, at this head. …"; thread 42 round 2 → a self-contained
  `**Low** — …` comment with the agreed fix; both `warnings=[]`.
- Tests cover: accept summarises a reply and apply posts exactly that body; accept stores a supplied
  text with zero model calls; a failing summariser falls back with a warning and still returns `200`;
  apply never re-summarises an accepted finding.

## Phase 18 — Sync by review id, Accept / Push back per round — 2026-11-08

Plan: `docs/plans/phase_18_plan.md`.

### Fixed

- **Sync no longer ignores comments by author.** `thread_sync` skipped anything written by the token's
  login, which in a single-account setup is the operator themselves: on review 12 four comments
  (`4506050804`, `4506051469`, `4506051796`, `4506052217`) were invisible and `/sync` reported "no new
  comments". Identity is now the GitHub id — a comment is ours only when its
  `pull_request_review_id` equals the id in `code_reviews.github_review_url`.
- **Root ids are recorded, and healed when they were missed.** `fetch_review_id_comments` reads
  `/pulls/{n}/comments` and filters on `pull_request_review_id` (the review-scoped endpoint returns
  `line: null`, which starved the matcher); matching tries anchor + body, then body, then anchor; the
  backfill also stores round 1's `published_github_comment_id`. Sync repairs AI threads that still have
  no root, by matching the text the tool posted.
- **A push-back now stops a finding.** Thread 4 of review 12 was published as `4506049104` even though
  the reviewer asked to push it back: the only lever was a round decision and the UI hid it for initial
  findings. Chat no longer promises removal (the discussion contract says so), and the decision exists
  on every round.

### Changed

- **Two decisions on every round**: `accept` (`pending_apply`, published by the next apply) and
  `push_back` (`resolved_no_reply`, nothing posted, `dropped` on an AI round 1 so the verdict prompt
  knows). `publish`/`resolve` remain aliases; a published round now returns `409` instead of being
  "resolved".
- AI round 1 starts as `pending_apply` ("Ready to apply") instead of `drafting`: apply already posted
  it, and the status now says so. `RoundPanel` shows Accept / Push back on every undecided round,
  initial findings included, and drops "Back to draft".
- `vcs.fetch_login` / `github_service.fetch_login` removed — nothing decides by author any more.

### Verified

- `pytest -q`: **180 passed** (177 + 3 new); `npm run build` green.
- Review 12 re-synced against the live PR: **1 new thread** (`4506052217`), **3 new rounds**
  (`4506050804`, `4506051469`, `4506051796`), and the four posted findings healed to roots
  `4506049093`, `4506049098`, `4506049104`, `4506049108` (round 1's published ids stored too). A second
  sync returns `0 / 0`; the review now holds 6 threads and 11 rounds.
- Tests cover: own-review comments skipped while same-author replies/openers arrive, healing a missing
  root and attaching the reply, push-back removing a finding from `comments_posted` (2 → 1), accept
  restoring it, and a new review's findings starting `pending_apply`.

## Phase 17 — Ad-hoc schema repair and fail-fast ingest — 2026-11-08

Plan: `docs/plans/phase_17_plan.md`.

### Fixed

- **`thread_messages.author` was missing from the operator database** (stamped `0011`, migrated with
  an earlier draft of 0009), so importing a PR's existing review comments failed with
  `psycopg.errors.UndefinedColumn: column "author" … does not exist` and killed the ingest task.
  Reviews 9, 10 and 11 sat at `running` / 36%. Repaired **ad-hoc, not by a migration**:
  `ALTER TABLE thread_messages ADD COLUMN author text` after the `information_schema` guard query;
  `alembic_version` stays `0011` and the procedure is written in the phase plan so another drifted
  database can be fixed the same way.
- **A crashed ingest can no longer hang a review.** `run_ingest` catches any exception, rolls back,
  logs the traceback, stores `failed` with `_short_error(exc)` (first line only, ≤200 chars — SQL
  parameters such as comment bodies never reach `code_reviews.error`) and publishes a terminal
  `error` event, so the workspace stops waiting instead of showing a spinner forever.

### Changed

- **No new Alembic revision.** An interim `0012_repair_thread_messages_author` was written and applied
  while diagnosing; at the operator's request it was removed and the database stamped back to `0011`
  *before* deleting the file. `alembic heads`, `alembic current` and `alembic upgrade head` all agree
  on `0011` again.
- Reviews 9, 10 and 11 were marked `failed` with an explicit cause naming the missing column; the
  operator chose not to recover them. `SELECT count(*) FROM code_reviews WHERE status='running'` is
  `0`.
- `README.md` (design-note bullet), `AGENTS.md` (§5 ingest boundary, §6 ad-hoc repair note),
  `CHANGELOG.md`.

### Verified

- `pytest -q`: **178 passed** (177 + the new `test_unexpected_ingest_error_fails_the_review`),
  CPython 3.11.14.
- Operator database (`code_review`): `thread_messages` has exactly one `author text NULL` column,
  `alembic_version = 0011` (head), `alembic upgrade head` is a no-op, and `alembic check` no longer
  reports `add_column thread_messages.author` (the pre-existing 0008-era index drift remains).
- Repaired path with real data: review 10's PR (#68978) fetched 5 comments → 5 threads and **flushed
  without error**, then rolled back — `review_threads` for 9/10/11 is still empty, nothing written.

## Phase 16 — Encrypt provider credentials at rest — 2026-11-08

Plan: `docs/plans/phase_16_plan.md`.

### Security

- **`version_control_keys.token` and `llm_keys.api_key` are encrypted at rest** with authenticated
  symmetric encryption (Fernet: AES-128-CBC + HMAC-SHA256), stored as `enc:v1:<token>` with a fresh
  nonce per write. The key comes from `CREDENTIALS_ENCRYPTION_KEY` and is never written to the
  database, so a stolen `pg_dump`, `app.db` or volume snapshot is inert without it. Threat model and
  limits (a compromised host or leaked `.env` is not covered) are in the plan and README.
- **`0011_encrypt_credentials`** — data-only revision (no DDL, so SQLite and PostgreSQL behave the
  same). Upgrade encrypts every plaintext row; downgrade decrypts them again. Upgrade **fails** when
  plaintext rows exist and no key is configured, leaving `alembic_version` at `0009` untouched.
- **`backend/app/core/crypto.py`** — envelope, key set (`MultiFernet`, first key encrypts, all
  decrypt), `CredentialKeyError` / `CredentialDecryptionError`; reads of pre-encryption plaintext are
  tolerated with a warning so a restored older backup still opens.
- **`backend/app/db/types.py::EncryptedText`** — column type that encrypts on bind and decrypts on
  load, so `vcs.py`, `apply_service.py`, `routes/models.py` and the schemas keep using `.token` /
  `.api_key` as plain strings instead of every call site encrypting by hand.
- **`backend/app/db/encryption.py`** — Core-SQL passes shared by the revision, the copy script, the
  rotation script and startup: `encrypt_plaintext`, `decrypt_all`, `reencrypt_all`, `plaintext_count`,
  `log_startup_report` (counts only, never values).
- **`scripts/generate_encryption_key.py`**, **`scripts/rotate_credentials_key.py`** — key generation and
  a repeatable rotation (`"<new>,<old>"`, re-encrypt, drop the old key).

### Changed

- `POST`/`PATCH` on `/api/keys/*` return **`503`** with an actionable detail when no key is configured;
  undecryptable rows return `503` on the key and settings reads. Registered as an app-level handler, so
  no route carries credential plumbing and the API still serves `/api/health`.
- `scripts/migrate_sqlite_to_postgres.py` encrypts copied rows inside its copy transaction (a source
  database written before 0011 would otherwise land as plaintext) and reports the count in `--dry-run`.
- **`alembic/env.py`** — `fileConfig(..., disable_existing_loggers=False)`: in-process migrations no
  longer disable the server's loggers at startup; `app` keeps INFO so the credential report is
  visible. This also restores uvicorn's own startup/access lines, which were being dropped.
- `README.md` (configuration row, "Credential encryption" section, Docker env, the two "plaintext by
  design" notes), `AGENTS.md` (§4 layout, §5 credentials, §10 rule), `backend/rules/privacy.md`
  (classification row), `backend/.env.example`.

### Verified

- `pytest -q`: **177 passed** (168 baseline + 9 new in `tests/test_credentials_encryption.py`),
  CPython 3.11.14.
- Scratch SQLite and scratch PostgreSQL (`code_review_check_p16`): `upgrade` encrypts, a second
  upgrade changes nothing, `downgrade -1` restores the exact plaintext, `upgrade` re-encrypts; a NULL
  `api_key` stays NULL.
- No-key upgrade on a seeded database: exit `1`, error names `CREDENTIALS_ENCRYPTION_KEY`,
  `alembic_version` stays `0009`, the row is unchanged.
- `pg_dump` of the scratch database (22,621 bytes): `0` hits for the plaintext token or API key, `2`
  rows carrying `enc:v1:`.
- Live uvicorn against the scratch PostgreSQL: signup `201`, credential create `201` with
  `token_masked: ghp_••••••••stuv`, `?reveal=true` returns the exact token, raw row
  `enc:v1:gAAAAABq8F…` (147 chars for a 40-char token), startup log
  `Credential encryption: keys=1 rows=4 plaintext=0`.
- Rotation: `--dry-run` reported 1 + 1 rows, the real run re-encrypted them, and dropping the old key
  still decrypted every row. Copy script dry-run reported "2 plaintext credential value(s) in the
  source"; the real copy landed them as `enc:v1:`.

## Phase 14 — Container image — 2026-11-08

Plan: `docs/plans/phase_14_plan.md`.

### Added

- **`Dockerfile`**: multi-stage build (Node 20 compiles the SPA, Python 3.11 slim runs the API),
  producing one non-root image on `:8000` with the backend, the built frontend and `code-review/`.
  Starts one uvicorn worker (SSE is in-process), runs `alembic upgrade head` on boot, stores SQLite
  and uploaded foundations in the `/data` volume, and ships a `/api/health` healthcheck.
- **`.dockerignore`**: keeps `.env`, local databases, `node_modules`, `dist/`, tests and uploaded
  foundations out of the build context.
- **`FRONTEND_DIR`**: optional setting that mounts a built SPA at `/` (history fallback for
  client-side routes, real assets still 404 when missing). Unset in development, so Vite keeps
  serving the UI; the image sets it to `/app/frontend/dist`.

### Changed

- `/` and other non-`/api` paths serve the compiled frontend when `FRONTEND_DIR` is set; `/api/*`,
  `/docs`, `/redoc` and `/openapi.json` keep priority because the mount is registered last.

### Verified

- `pytest -q`: 167 passed, including the new mount/deep-link/asset test.
- `npm run build` green.
- Image built and run on a scratch volume: `/api/health` 200, `/` and `/reviews/1` return the SPA,
  hashed assets load, missing assets 404, and the Alembic schema is created in `/data/app.db`.

## Phase 13 — Existing GitHub comments and multi-round discussions — 2026-11-08

Plan: `docs/plans/phase_13_plan.md`.

### Added

- **Existing PR comments at ingest**: every review comment on the pull request is fetched, grouped
  by root comment and stored as a `GITHUB_EXISTING` thread with its full history, author, line and
  hunk — next to the AI findings, in the same workspace.
- **`thread_rounds`**: one row per inbound comment or queued reply (`drafting`, `pending_apply`,
  `published`, `resolved_no_reply`), so a thread can be discussed repeatedly without losing which
  message each reply answers.
- **`POST /api/reviews/{id}/sync`**: appends unseen replies as new rounds, creates threads for new
  top-level comments, ignores the authenticated account's own comments, and is idempotent by GitHub
  comment id.
- **`POST /api/reviews/{id}/rounds/{round_id}/decision`**: queue a round for publishing, close it
  without a reply, or reopen it.
- **Delta apply**: one formal review for unposted AI findings (with comment ids backfilled so replies
  thread correctly), then one `…/comments/{id}/replies` call per queued round. `replies_posted` is
  reported; a second apply with something pending publishes only the new work.
- **Workspace filter bar** with counts (`All`, `AI Findings`, `GitHub Threads`, `Needs Response`),
  origin-specific rails/badges, collapsible historical rounds, and a dynamic apply label.

### Changed

- **Discussing a closed round opens a new draft round** instead of silently appending to a published
  one, so an existing discussion can be answered with the copilot.
- An apply with nothing pending is a `409`; previously any second apply was refused, which made
  answering a new GitHub reply impossible.
- Prompts label external messages with their GitHub author and their round.

### Database

- `0009_thread_rounds`: `origin`, `github_root_comment_id`, `original_author`, `current_round` and
  `thread_status` on `review_threads`; the `thread_rounds` table; `round_number`, `is_external`,
  `author` and `github_comment_id` on `thread_messages`. Existing threads are backfilled with one
  round holding their last conclusion — nothing is dropped.

### Verified

- `pytest -q`: 168 passed, 12 of them added here — grouping, ingest, sync (reply, new root,
  self-author, idempotency), round decisions, delta apply, resolution and the GitLab notice.
- `npm run build` (tsc + vite) green.
- `0009` upgraded, downgraded and re-upgraded on `sqlite:////tmp/p13-verify.db`.
- Live run against a local GitHub/Ollama mock on a scratch database: ingest stored 1 imported thread
  (2 external messages) and 2 findings; a mock reply synced to round 2 (`0 new threads / 1 new
  round`); discussion + queue + apply posted 1 review with 2 inline comments and 1 threaded reply,
  backfilled root ids `9001`/`9002`; a new top-level comment synced as a new thread; the second sync
  reported `0 / 0`; an empty apply returned `409`. The UI showed `All (4) / AI (2) / GitHub (2)` and
  `Apply 1 pending reply`, which posted exactly one reply and then read `Everything applied`.

## Phase 12 — Accounts with private credentials — 2026-11-08

Plan: `docs/plans/phase_12_plan.md`.

### Added

- **Accounts**: `users` (email + salted PBKDF2-SHA256 password hash) and `sessions` (SHA-256 of a
  random cookie token, 14-day expiry). `POST /api/auth/signup|login|logout`, `GET /api/auth/me`;
  the session lives in an HttpOnly, SameSite=Lax cookie, so no token is ever exposed to JavaScript.
- **Ownership**: `user_id` on `version_control_keys`, `llm_keys`, `code_reviews` and `settings`
  (one settings row per account). Every route depends on `get_current_user` and scopes its queries;
  another account's key or review is a `404`, not a `403`.
- **Per-account credentials**: each account keeps its own GitHub/GitLab tokens and Claude/OpenAI/
  Ollama keys with its own active selection. Background jobs resolve keys through the review owner.
- Frontend: `AuthProvider`, `/login`, `/signup`, a `RequireAuth` guard, and the signed-in email plus
  sign-out in the nav.

### Changed

- Migration `0008_users_and_ownership` adds the two tables and the four `user_id` columns, then
  enforces NOT NULL and a unique `settings.user_id`. Existing rows are attached to a disabled
  `legacy@localhost` account (no usable password hash) instead of being dropped.
- `settings` is no longer a singleton: `get_or_create(db, user_id)`.
- The frontend only mounts `SettingsProvider` behind the guard, so a signed-out visit no longer
  fires an authenticated request.

### Verified

- Migration round-tripped on scratch SQLite and PostgreSQL (`upgrade → downgrade 0007 → upgrade`),
  including the legacy backfill (owner assigned, `verify_password(..., '!')` false).
- 152 backend tests pass, including `tests/test_auth.py` (hash round-trip, duplicate, weak password,
  bad email, wrong password, logout, 401 on every private route, hashed-at-rest sessions, expiry)
  and `tests/test_isolation.py` (cross-account keys, settings and reviews are invisible and
  unreadable); `npm run build` clean.
- Live: two accounts created over HTTP; B listed no keys, `needs_setup: true`, and got `404` for
  A's review, events, discuss and apply; A's review ran with A's GitLab + Ollama keys; logout made
  the same call `401`.
- Browser: signed-out `/` → `/login`; sign-up → `/setup` with the new email in the nav; sign-out →
  `/login`; signing in as the account that owns a review showed that review and no one else's.

---

## Phase 11 — Re-evaluated verdict & `#` autocomplete — 2026-11-08

Plan: `docs/plans/phase_11_plan.md`.

### Added

- **Verdict re-evaluation** (`app/services/verdict.py`): after a discussion submit, one extra model
  call reads every thread — original finding, latest conclusion, reviewer's last message, withdrawn
  marker — and returns `{verdict, confidence, rationale}`. The review's opinion is updated and
  returned in the same response.
- **`code_reviews.suggested_verdict_note`** (migration `0007_verdict_note`): one line explaining the
  opinion, surfaced under the AI opinion in the action bar.
- **`DiscussResponse.opinion_refreshed` / `warnings`**: tells the UI whether the opinion moved, and
  why it did not.
- **`#` mention picker** (`MentionMenu.tsx`): typing `#` in a composer lists this review's threads
  (ordinal, `path:line`, excerpt), digits filter, `↑`/`↓` move, `Enter`/`Tab`/click insert `#N`,
  `Esc` and blur close. The thread being edited is excluded.

### Changed

- `POST /api/reviews/{id}/discuss` now performs one review-level call in addition to the per-thread
  replies; the verdict pass is advisory — a provider error, timeout or unparsable answer keeps the
  previous opinion and adds a warning instead of failing the submit.
- The action bar shows the refreshed verdict, its confidence and the rationale; submitting reports
  "AI opinion updated to APPROVE (88%)" in the notice line.

### Verified

- 140 backend tests pass (8 new in `tests/test_verdict.py`: normalisation, prompt shape, refresh,
  failure isolation, unparsable answer); `npm run build` clean.
- Live run: ingest produced `REQUEST_CHANGES · 79`, a discussion submit moved it to `APPROVE · 88`
  with the rationale persisted, `opinion_refreshed: true`.
- Browser: typing `#` listed `#2 · app/services/token_verifier.rb:15 · **Low** — …`, `2` filtered
  to that one entry, `Enter` produced `Refer to #2 ` and closed the menu; the footer showed
  "Approve · 88%" with its rationale.

---

## Phase 10 — Provider credentials (GitLab + more LLMs) — 2026-11-08

Normalises credentials instead of keeping one GitHub token and one model's keys in `settings`, and
adds GitLab merge-request support. Plan: `docs/plans/phase_10_plan.md`.

### Added

- **`version_control_keys`** table: one row per token (`github` | `gitlab`), optional `base_url`
  for self-hosted GitLab, optional label.
- **`llm_keys`** table: one row per provider (`claude` | `openai` | `ollama_cloud` |
  `ollama_local`) with `api_key`, `base_url` and an optional `default_model`.
- **Migration `0006_provider_keys`**: creates both tables, adds `settings.version_control_key_id`
  / `settings.llm_key_id` and `code_reviews.vcs`, backfills existing credentials into rows, then
  drops the six legacy columns. Downgrade restores them from the active keys.
- **Keys API**: `GET|POST /api/keys/version-control`, `PATCH|DELETE /api/keys/version-control/{id}`,
  `POST /api/keys/version-control/{id}/test`, and the same set under `/api/keys/llm`. Secrets stay
  masked unless `?reveal=true`.
- **GitLab support** (`app/services/gitlab_service.py`): merge-request URL parsing (nested groups,
  self-hosted hosts), `GET /projects/:id/merge_requests/:iid`, paginated `/diffs` re-rendered as a
  unified diff, `diff_refs` captured for inline positions, notes/discussions/approve.
- **Provider dispatch** (`app/services/vcs.py`): `PullRef`, `parse_pr_url`, `fetch`, `fetch_diff`,
  `publish` — GitHub and GitLab behind one interface, with the mandated body in one place.
- **OpenAI transport** (`openai:<model>`): chat completions, `/models` listing, `response_format`
  JSON mode, `OPENAI_BASE_URL` override.
- **Credential resolution** (`app/services/keys_service.py`): active key first for the requested
  provider, otherwise the oldest key of that provider — so a review keeps working when the operator
  switches the active credential.

### Changed

- **`settings` is now pointers, not secrets**: `{version_control_key_id, llm_key_id}` plus a
  read model that resolves both into masked summaries. `needs_setup` is true until both resolve.
- `POST /api/settings` patch semantics: an absent field leaves the selection, an explicit `null`
  clears it.
- `GET /api/models` is built from the configured keys and returns `preferred` (the active key's
  `default_model`) instead of `ollama_mode`.
- `POST /api/reviews` resolves the token from the URL's host (GitHub or GitLab) and the model's
  credential from its prefix; `code_reviews.vcs` records the host for apply.
- Publishing: GitHub keeps one review with inline comments (and the 422 body-only retry); GitLab
  posts one note plus one discussion per finding and attempts an approval for `APPROVE`.
- `POST /api/settings/test-connection` now targets `version_control` and `llm` (the active keys).

### Removed

- `settings.github_token`, `claude_api_key`, `ollama_api_key`, `ollama_mode`, `ollama_base_url`,
  `ollama_model` — replaced by the two key tables.
- The `GITHUB_API_URL`-only endpoint configuration: a key may pin its own base URL, with the env
  var still acting as the default.
- The old `SecretField` component (the key manager replaces it).

### Fixed

- Migration `0006` is dialect-agnostic (`batch_alter_table`), so the schema round-trips on both
  SQLite and PostgreSQL; verified `upgrade head` → `downgrade 0005` → `upgrade head` on both.

### Verified

- Migration `0006` up/down/up on both SQLite and PostgreSQL, with the backfill producing one
  `github` key, one `claude` key and one `ollama_cloud` key (carrying the old default model) from
  a legacy settings row.
- 132 backend tests pass; `npm run build` passes (tsc + vite).
- Live run against a mock GitLab (`/api/v4`) and mock Ollama: an MR URL ingested with a converted
  unified diff, findings anchored to lines 14/15, `code_reviews.vcs = gitlab`, discussion worked,
  and Apply posted the mandated note plus one discussion per thread with
  `base_sha`/`start_sha`/`head_sha`/`new_path`/`new_line`, followed by `POST /approve`.
- Settings UI renders both families with masked secrets, active selection, per-key test and delete;
  the review header shows `GitLab · group/project!7`.

---

## Phase 9 — PostgreSQL as the application database — 2026-11-08

Plan: `docs/plans/phase_9_plan.md`.

### Added

- **`backend/scripts/migrate_sqlite_to_postgres.py`**: rake-style copy task. Applies migrations to
  the target, refuses a non-empty target without `--truncate`, copies parents-first in one
  transaction, re-attaches UTC on `timestamptz` columns, resets id sequences, re-counts both sides
  and rolls back on mismatch. Supports `--source`, `--target`, `--dry-run`.
- `tests/test_db_migration_script.py`: URL resolution, UTC coercion, refusal guards.
- Startup logs the resolved database and skills paths.

### Changed

- **PostgreSQL is the default** (`postgresql+psycopg://localhost:5432/code_review`); `psycopg` 3
  added to `requirements.txt`, `backend/.env` now points at the local database.
- SQLite remains supported — the test suite runs on a temporary SQLite file.
- README: requirements, `createdb` step, env table and a dedicated migration section.

### Fixed

- Naive SQLite timestamps no longer shift by the server's offset when copied into PostgreSQL.

---

## Phase 8 — Cross-referencing, verdict opinion & finalisation — 2026-11-07

Plan: `docs/plans/phase_8_plan.md`.

### Added

- **`#N` cross-references** in discussion messages: resolved to the referenced thread's file, line,
  original finding and latest conclusion, then appended to the model prompt as a "Referenced
  threads" block. Chips in the UI jump to that thread.
- **AI verdict + confidence**: the review contract accepts `{verdict, confidence, findings}` (bare
  arrays still accepted), stored as `code_reviews.suggested_verdict` /
  `confidence_percentage` (migration `0005_review_intelligence`) and shown in the action bar with
  a one-click "use it".
- **Summarise + prune pass** (`app/services/summarise.py`) before publishing: one GitHub-ready
  comment per thread, and a thread is withdrawn when the model conceded during discussion.
  `review_threads.summary` / `dropped` added.
- Migration `0005`: `suggested_verdict`, `confidence_percentage`, `summary`, `dropped`.

### Changed

- Publishing body is fixed to
  `Code review completed with {n} inline findings, discussed and verified by human - By Code Review Master`,
  where `n` counts the comments that survived pruning. The free-text summary field is gone.
- Withdrawn threads are excluded from the payload and surfaced as a warning.
- The summariser is best-effort: on failure, publishing falls back to the last message per thread.

### Fixed

- Dropped threads are reported in the apply response (`dropped[]`) and rendered with a `withdrawn`
  badge instead of silently vanishing.

---

## Phase 7 — Skill management & process visibility — 2026-11-07

Plan: `docs/plans/phase_7_plan.md`.

### Added

- **Skills tab (`/skills`)**: browse the library, upload a single `.md`/`.txt`, and manage **Core
  Skill Foundations** created from a folder or a `.zip` (single wrapper folder stripped, markdown
  only, traversal/symlink/size/entry-count guards, default foundation protected from deletion).
- **Foundation selection** per review, stored in `code_reviews.skill_foundation` (migration `0004`)
  and reused for that review's discussions.
- **Live progress over SSE**: `POST /api/reviews` returns `202` and the job streams
  `progress`/`done`/`error` events on `GET /api/reviews/{id}/events`, with history replay for late
  subscribers and orphaned `running` rows reconciled to `failed` at startup.
- **Copy context** action on each discussion card (`path:line` + diff hunk).

### Changed

- Review creation moved from a blocking request to a background job; cheap validation still
  happens on the request so bad input is a `4xx`, not a failed job.
- Progress text replaces the static "the model reads the diff…" placeholder.

### Removed

- The blocking ingest path from the HTTP request handler.

---

## Phase 6 — Ollama Cloud as the default & first-run guide — 2026-11-07

Plan: `docs/plans/phase_6_plan.md`.

### Added

- **Ollama Cloud** (`https://ollama.com`, bearer API key) as the default Ollama transport, with the
  local daemon kept as an explicit alternative. Migration `0003` adds `ollama_api_key` and
  `ollama_mode`, backfilling existing non-cloud rows to `local`.
- **`/setup` guide** shown instead of the dashboard until a version-control token and a model
  credential exist (`needs_setup` is server-derived).
- Distinct model-id prefixes `ollama-cloud:` and `ollama-local:`; legacy `ollama:` resolves to
  cloud.

### Fixed

- A review keeps its transport after Settings change, because the prefix is persisted in
  `model_used`.

---

## Phase 5 — Publish to GitHub — 2026-11-07

Plan: `docs/plans/phase_5_plan.md`.

### Added

- `POST /api/reviews/{id}/apply`: one GitHub review with inline comments (`path`, `line`,
  `side: RIGHT`), a verdict (`APPROVE` / `REQUEST_CHANGES` / `COMMENT`) and a summary body.
- Comment bodies come from the agreed conclusion of each thread, prefixed with
  `**AI Review Conclusion:**` when the thread was actually discussed.
- Applied reviews record the verdict and review URL and refuse a second apply (`409`).

### Fixed

- Anchors are re-validated against the **current** diff before posting; one invalid anchor makes
  GitHub reject the entire review, so a `422` retries body-only and surfaces a warning.

---

## Phase 4 — Interactive discussion — 2026-11-07

Plan: `docs/plans/phase_4_plan.md`.

### Added

- `POST /api/reviews/{id}/discuss`: bulk submit, one model call per thread via
  `asyncio.gather`, per-thread success/failure in the response.
- Reviewer messages are persisted before the model call, so a failed thread keeps its input and the
  draft can be retried.

### Fixed

- Discussion replies are plain prose — Ollama's `format: json` is applied to review generation only,
  otherwise the model was forced into JSON for chat.

---

## Phase 3 — Review workspace — 2026-11-07

Plan: `docs/plans/phase_3_plan.md`.

### Added

- Split-pane workspace: code context on the left, discussion cards on the right, linked selection
  and matching ordinals.
- Sticky action bar with verdict selection, bulk submit and apply.
- Dashboard listing of reviews with status, model and thread count.

### Fixed

- Stored diff snippets are rebuilt from the parsed hunk rather than trusting the model's quoted
  context.

---

## Phase 2 — Ingestion, anchoring & prompting — 2026-11-07

Plan: `docs/plans/phase_2_plan.md`.

### Added

- GitHub PR parsing and fetch of metadata + unified diff (`application/vnd.github.v3.diff`).
- Diff parser that skips lockfiles, minified/binary/generated files and vendored trees, and anchors
  findings to real RIGHT-side lines.
- Relevance-budgeted skill library loading and the review output contract (strict JSON findings).
- Review persistence: `code_reviews`, `review_threads`, `thread_messages`.
- Model dispatch for Claude and Ollama, with JSON extraction tolerant of fences and prose.

---

## Phase 1 — Foundation — 2026-11-07

Plan: `docs/plans/phase_1_plan.md`.

### Added

- FastAPI backend, React/Vite frontend, SQLAlchemy 2.0 + Alembic (`0001_initial_schema`).
- Singleton `settings` row with masked-by-default secrets, `GET`/`PUT /api/settings`,
  connection probes that return failures as data.
- Local-first model: nothing leaves the machine except the diff sent to the chosen provider.

---

## Housekeeping (across phases)

- **Reverted** — phase 18 (workspace panes filling the space above the action bar) was backed
  out at the operator's request. `SplitPane` keeps its `62vh`/`64vh` pane caps and
  `ReviewDetailPage` keeps `pb-44`; the `--action-bar-h` measurement in `StickyActionBar`
  is gone with it, and `docs/plans/phase_18_plan.md` was removed so the plan folder still
  describes only what shipped.
- **Fixed** — uvicorn's reloader always watches the working directory; the documented start command
  uses `--reload-exclude` patterns so editing a test does not restart the server mid-review.
- **Fixed** — database verification uses throwaway URLs. The real database is never deleted or
  truncated to "start clean" (see `AGENTS.md` → Database).
- **Added** — `AGENTS.md`: plan-first rule, architecture, conventions, definition of done;
  `docs/plans/phase_1_plan.md` … `phase_10_plan.md`; `README.md`; `.gitignore`.
- **Added** — folder-scoped rules: `backend/rules/` and `frontend/rules/` refine the root
  `AGENTS.md` for their area, and the next phase number is read from `docs/plans/` rather than
  hardcoded.
- **UI polish** — copy-file-path icon on the code panel, `Copy context` on the discussion card,
  open-in-GitHub link on the review title, AI verdict + confidence in the action bar.