# INITIATIVES — what to build next

Last updated: 2026-11-08 · Covers phases 1–20 (phase 21, S3 skill storage, is still a design
record only).

This file is a backlog, not a plan. Each entry below is a candidate feature with enough evidence
that the first question — *is this a real gap?* — is already answered. Per `AGENTS.md` §1, no
application code starts until a `docs/plans/phase_<N>_plan.md` exists for the chosen initiative,
so every idea here names what that plan would have to decide.

Ideas are ranked by **value ÷ effort**, not by how interesting they are to build.

| # | Initiative | Why it matters | Effort | Schema |
|---|------------|----------------|--------|--------|
| 1 | Repository context for the model | Fewer false findings, grounded discussions | L | no |
| 2 | ~~Multi-pass review of large diffs~~ | Shipped in phase 26 — see §2 for the deviations | M–L | no |
| 3 | ~~Watch a PR and review new commits~~ | Shipped in phase 27 — see §3 for the deviations | XL | yes |
| 4 | ~~LLM call ledger and quality analytics~~ | Shipped in phase 22 — see §4 for the deviations | M | yes |
| 5 | Streaming replies, per-thread retry, cancel | The most visible UX wart in the product | L | no |

---

## 1. Repository context: let the model read the code it is reviewing

**Problem.** The model sees exactly two things: the loaded skill library and the numbered diff
(`services/prompts.build_user_prompt`). It never sees the rest of the file, the callers of the
function it is commenting on, or the tests that exercise it. `README.md` states the consequence
plainly: *"Discussions see the anchored hunk, not the repository."*

The failure modes are predictable and were visible in real reviews:

- A finding claims a method does not exist — it is defined 40 lines above the hunk.
- A change is flagged as safe while every caller in the repo passes `nil`/`None` for the new
  required argument.
- A discussion asks "is this used anywhere?" and the assistant can only say "I cannot see the
  wider codebase", which is the least useful sentence in the product.

**Proposal.** Add a context layer that runs after the diff is fetched and before the prompt is
built:

1. **Full file at the PR head** for every changed file that survived the diff parser — the
   post-change content, fetched by path at `commit_id`. This is the highest-value single addition;
   most "impossible" questions are answered by the file itself.
2. **Base version** of the same file, only for discussions that ask about previous behaviour
   (optional second-tier budget).
3. **Neighbours by reference** (v2): files that mention a changed symbol, found through GitHub's
   code-search endpoint where the token has scope, GitLab's search API otherwise. Bounded to a
   handful of files per review.
4. **Budget arbitration.** One shared character budget (starting at 30 000 chars, alongside the
   existing 60 000 for the diff), spent changed-file-first, then neighbours by relevance. Every
   truncation is announced in the prompt *and* recorded as an ingestion note, the same way the
   diff cut is today.

Cache by `(repo_full_name, commit_id, path)` so a discussion on the same review does not re-fetch
ten files ten times. A database table is the portable cache: `/tmp` is per-instance on Vercel and
the local filesystem is not shared either.

**Design decision the phase plan must make.** Context is fetched at ingest and frozen with the
review, or re-fetched per discussion? Freezing is reproducible and cheap; re-fetching is fresher
but can contradict the anchors. Recommendation: freeze at ingest, re-validate the commit id at
discuss time and warn if the branch has moved.

**Touch points.**

- `backend/app/services/vcs.py` + `github_service.py` / `gitlab_service.py` — `fetch_file(path, ref)`.
- New `backend/app/services/context_service.py` — selection, budget, cache, truncation notes.
- `backend/app/services/prompts.py` — a `<repository_context>` section with explicit provenance
  per file ("contents at commit abc123").
- `backend/app/services/review_pipeline.py` — fetch between parse and prompt; new progress stage.
- `backend/app/core/config.py` — `context_max_chars`, `context_max_files`.
- Migration only if the cache is a table (recommended: `0013_file_cache` or a later number,
  whichever is free at implementation time).

**Risks.**

- **Tokens and latency.** A 20-file PR adds tens of thousands of input tokens per call. The budget
  and the per-file cap are the control; measure cost per review before/after (see initiative 4).
- **Privacy.** More source leaves the machine, to the same provider that already received the
  diff. This does not change the trust boundary, but the README's privacy note must say so.
- **Rate limits and serverless time.** N contents calls per review inside a function with a
  request-level timeout; fetch concurrently with a hard cap.

**Verification.** A stubbed `fetch_file` test asserting the prompt contains the full post-change
file and no base version; a budget test proving the oldest/least-relevant file is dropped first;
an anchoring test proving context cannot introduce new anchors; a discussion test where the answer
depends on a line outside the hunk and is correct only with context enabled.

---

## 2. Multi-pass review for large diffs — shipped, phase 26

> Built as `docs/plans/phase_26_plan.md`. Three deviations from the sketch below: there was no
> "existing global finding cap" to apply, so `review_max_findings` (60) was introduced and applies
> to single-pass reviews too; splitting is triggered by `diff_max_chars`, not by the part size, so a
> 40 000-character diff is still one call and only a change that *would* have been truncated is
> chunked; and the merge pass anchors against the full diff before deduping, since parts own
> disjoint files and a per-line key is enough. Truncation now cuts on hunk boundaries rather than
> mid-line. Verified end to end: a 130 876-character, 16-file diff produced 8 ingest calls plus one
> verdict call, 16 anchored findings, and no truncation warning.

**Problem.** A review is one model call over one diff, hard-capped at
`diff_max_chars = 60_000` (`core/config.py:52`). Past that the diff is truncated and the review
records *"The diff was truncated to fit the model context."* (`review_pipeline.py:353-355`).
`README.md` is explicit: *"Large diffs are truncated, not chunked."*

For a real feature PR this is not a corner case — 60 000 characters is roughly 1 500 changed
lines. Everything after the cut is unreviewed while the UI still presents the result as complete.

**Proposal.** Replace the single call with a bounded fan-out:

1. **Partition by file.** Greedily pack changed files into units under `review_unit_chars`
   (default ~25 000). Never split a hunk; a single file larger than the unit budget gets its own
   oversized unit with an explicit note.
2. **One call per unit, concurrently.** Same system prompt (skills + contract); the user prompt
   gains "This is part *i* of *n*. Report findings only in the files listed below." Cap
   concurrency (`llm_review_concurrency`, default 3) so a cloud provider is not rate-limited and
   a local model is not thrashed.
3. **Merge.** Concatenate findings, anchor each against the full parsed diff as today, dedupe on
   `(path, line, normalised title)` keeping the longest body, then apply the existing global
   finding cap.
4. **One verdict pass** over the merged findings, reusing the phase 11 `{verdict, confidence,
   rationale}` prompt shape, so `suggested_verdict` still exists for single-pass and multi-pass
   reviews alike.
5. **Partial failure policy.** All units failed → review fails (today's behaviour). Some units
   failed → publish the findings that did land, keep `failed` units in the ingestion notes, and
   surface them in the warnings banner. Never silently present a partial review as complete.
6. **Progress.** One `review_events` row per unit: "Reviewing 14 files (part 2 of 4)…", using the
   existing bus — no new transport.

**Touch points.** `review_pipeline.execute` (split the prompt/call/anchor block into a
`_review_unit` helper), `prompts.build_user_prompt` (part-of-n framing), `core/config.py`
(`review_unit_chars`, `llm_review_concurrency`), `services/progress.py` (stage text only),
`frontend` (nothing, the progress stream already renders arbitrary stages), tests.

**Risks.**

- **Cost grows with PR size.** That is the point, but it must be visible — which is why initiative
  4 is the natural companion.
- **Duplicate findings across units** when two files in different units are the same defect.
  Dedupe on path+line solves the common case; cross-unit duplicates need a normalised-title check
  and will still leak some.
- **Inconsistent severity between units.** The verdict pass can reconcile the overall opinion, not
  the per-finding text. Acceptable; note it in the plan.

**Verification.** A synthetic 150 000-char diff produces ≥3 units and every finding is anchored; a
dedupe test with the same finding emitted twice; a unit-failure test proving the review is
`draft` with warnings rather than `failed`; a test that a single-file PR still makes exactly one
model call.

---

## 3. Watch a PR and review new commits (delta reviews) — shipped, phase 27

> Built as `docs/plans/phase_27_plan.md`. Deviations from the sketch below: a watch is created
> **from an existing review** (`POST /api/watches {review_id}`, which copies the model and
> foundation) rather than from a dashboard form or an apply checkbox — one fewer form and one
> explicit enable; the "parent" link is stored twice (`parent_review_id` for the UI,
> `watch_id` on the review for idempotency, plus `UNIQUE(watch_id, commit_id)`, which the sketch
> only implied); `last_seen_commit_id` advances when the delta review is **created**, not when it
> succeeds, so one flaky model call cannot re-review the same commit on every tick; and the tick
> runs its reviews inline (locally in the loop, on Vercel inside the cron request) instead of
> spawning background tasks, because `asyncio.create_task` dies with the response. Verified end to
> end: a moved mock head produced one linked review, one `compare(old…new)`, zero full-diff
> fetches, and a second tick that did nothing.

**Problem.** A review starts from a pasted URL and ends at `applied`, which is terminal — a second
apply is a `409`. The review is pinned to the `commit_id` recorded at ingest. Reviewing the
author's fixes therefore means pasting the URL again, which produces an unrelated review whose
threads do not continue the conversation and whose imported comments are re-read from scratch.

The product is built for the loop (rounds, decisions, sync) but cannot start the next iteration
itself. There is no webhook, no polling, and no notion of a review's successor:
`code_reviews` has `commit_id` but no `parent_review_id` and no trigger column.

**Proposal.** A "watch" on a pull/merge request:

1. **`review_watches`** — `id, user_id, vcs, repo_full_name, pr_number, pr_url, foundation, model
   key, last_seen_commit_id, enabled, created_at`. Created from the dashboard ("Watch for new
   commits") or automatically on apply, as a checkbox.
2. **Change detection.** Compare `last_seen_commit_id` with the current PR head.
   - Locally/Docker: an asyncio loop started with the app, one tick every `watch_interval_minutes`
     (default 10), skipped entirely when `SERVERLESS=true`.
   - Serverless: `POST /api/watches/tick`, authenticated by a shared secret header, called by
     Vercel Cron. One tick must be idempotent and must not double-review.
3. **Delta diff.** Fetch `compare/{old}...{new}` (GitHub) / `compare?from=…&to=…` (GitLab) and
   review only the new commits' diff. Existing comments are still fetched so imported threads and
   replies stay in one workspace.
4. **Linked review.** A new `code_reviews` row with `parent_review_id` set, `trigger='watch'`, a
   "Continues review #12" header link, and a warning that anchors not in the delta are not
   re-validated. Apply posts a follow-up review with only its own pending rounds.
5. **Notifications.** Out of scope for v1 beyond a dashboard badge ("new commits on #72058 —
   review started"). No email, no Slack.

**Touch points.** New `models/watch.py`, `services/watch_service.py`, `api/routes/watches.py`;
`code_reviews.parent_review_id` + `trigger`; migration; `vcs.py` compare support;
`review_pipeline.execute` accepting a diff override instead of always fetching the full one;
`frontend` dashboard watch toggle, badge, and "continues #N" header line; `vercel.json` cron entry.

**Risks.**

- **Highest complexity of the five.** New lifecycle (watch → review → review), two scheduling
  models, and a new failure mode: a watch that silently stops firing.
- **Quota.** Every tick costs one PR-metadata call per watch. Batch and back off; do not run on a
  1-minute interval.
- **Delta anchoring.** A comment on a line untouched by the delta cannot be posted to that
  review; the apply step must drop it with a warning rather than fail (the phase 5 rule already
  exists for stale anchors).
- **Review spam.** A PR with ten pushes becomes ten reviews. Default the watch to off, require an
  explicit enable, and collapse pushes newer than the last reviewed commit into one delta.

**Verification.** A fixture `compare` payload creates a linked review whose diff contains only the
new file; a second tick with an unchanged head is a no-op; two ticks racing produce one review
(the unique constraint on `(watch_id, commit_id)` or a row lock); the serverless mode has no loop
and the endpoint rejects a missing secret; applying the delta review posts exactly its pending
rounds.

---

## 4. LLM call ledger and review quality analytics — shipped, phase 22

> Built as `docs/plans/phase_22_plan.md`. Two deviations from the sketch below: `llm_calls` has no
> `user_id` (ownership is joined through `code_reviews`, so the two cannot disagree) and analytics
> has its own page rather than a dashboard panel. The rest — a `purpose` per call, NULL-tolerant
> token columns, a prefix-matched price table labelled *estimated*, acceptance/push-back rates per
> model and soft caps — is as described.

**Problem.** The app cannot answer "what did this review cost?" or "which model is actually
better?". `llm_service` sends `max_tokens` and never reads the response's `usage` block, so input
and output tokens are discarded for all three provider families. Nothing records latency, and
nothing records whether an AI finding survived discussion. The dashboard
(`GET /api/reviews`) is an unfiltered list ordered by `created_at`.

Provider choice is therefore folklore. Phase 11 already computes a confidence and a rationale;
phase 19/20 already decide which rounds were accepted — the data needed for a real comparison is
produced and then thrown away.

**Proposal.**

1. **`llm_calls`** — one row per provider call: `id, user_id, review_id, thread_id (nullable),
   purpose (ingest | discuss | verdict | summarise), provider, model, prompt_tokens,
   completion_tokens, latency_ms, ok, error_class, created_at`. No prompt or completion text is
   stored — counts only, per `rules/privacy.md`.
2. **Parse usage per adapter.** Anthropic `usage.input_tokens/output_tokens`; OpenAI
   `usage.prompt_tokens/completion_tokens`; Ollama `prompt_eval_count/eval_count` (absent on some
   local models — record `NULL`, not zero). Streaming, when initiative 5 lands, must merge usage
   from the final event.
3. **Price table in config**, `model_prices` as `{model_prefix: {input, output}}` in USD per
   million tokens, marked as an estimate. Unknown models show tokens only. Never hard-fail on a
   missing price.
4. **`GET /api/analytics?days=30`** — totals by day, by model, by purpose; average and p95
   latency; **acceptance rate** = AI findings whose round ended `published` ÷ all AI findings;
   **push-back rate**; reviews by status. All computed in SQL, no Python post-processing.
5. **UI.** A small strip on the dashboard (spend this month, tokens, median latency, acceptance
   rate) and one line in the review header ("4 calls · 61k tokens · ~$0.09 · 2m14s"). Analytics is
   a panel on the existing dashboard, not a new page.
6. **Soft budget.** Per-user monthly token/dollar ceiling; crossing 80% shows a banner, crossing
   100% warns on new-review submit. It does not block — a hard block in a local tool is hostile.

**Touch points.** New `models/llm_call.py`, migration, `services/llm_service.py` (return usage
alongside text; a small `LLMResult` dataclass rather than widening tuples), `review_pipeline`,
`discussion`, `verdict`, `summarise` (pass `purpose` and `thread_id`), new
`api/routes/analytics.py`, `schemas/analytics.py`, `frontend` dashboard strip + review header +
`types/index.ts`.

**Risks.**

- **Price staleness.** Prices change; the UI must label every dollar figure "estimated" and the
  table must be data, not code sprinkled through the service.
- **Write amplification.** One extra insert per model call. Trivial at this scale; keep the insert
  outside the review transaction so a ledger failure never fails a review.
- **Metrics that mislead.** Acceptance rate is a proxy for quality, not quality. Label it and do
  not build a leaderboard that encourages gaming it.

**Verification.** Per-adapter tests with recorded provider payloads asserting token counts;
a `NULL`-tolerance test for a local Ollama response with no counts; an aggregate test over a fixed
fixture asserting totals, p95 and acceptance rate; a test that a failing call is still recorded
with `ok=false` and an `error_class`; a manual run showing a non-zero dollar figure for a real
review.

---

## 5. Streaming replies, per-thread retry and cancel

**Problem.** `POST /api/reviews/{id}/discuss` runs every thread through `asyncio.gather` and
returns when the slowest one finishes. The UI shows a per-card spinner until then. With a local
`gemma4:31b` that is a minute or more of nothing, and the entire submit is hostage to the slowest
thread. `README.md` lists "No streaming" as a known limitation, and phase 4 explicitly deferred
per-thread retry: *"re-typing the draft and submitting again is the retry."* There is also no way
to stop a submit once it started.

**Proposal.**

1. **Streaming endpoint.** `POST /api/reviews/{id}/discuss/stream` returns
   `text/event-stream` with events `{type: "thread_started", thread_id}`, `{type: "delta",
   thread_id, text}`, `{type: "thread_done", thread_id, message_id}`, `{type: "thread_error",
   thread_id, error}`, and a terminal `done`. Keep the JSON endpoint unchanged for compatibility
   and for tests.
2. **Provider streaming.** Anthropic SSE (`content_block_delta`), OpenAI `stream=true` deltas,
   Ollama NDJSON lines. One `stream_chat()` per adapter that yields text chunks and resolves a
   final usage record (feeds initiative 4).
3. **Persist per thread, as it finishes.** Each completed thread writes its user + assistant
   messages and transitions the review `draft → in_discussion` inside its own short transaction.
   This is what makes cancel and partial failure correct: finished work is never lost.
4. **Cancel.** Client aborts the fetch; the server's request task is cancelled and the gather is
   torn down. Threads that had already completed stay persisted and are reported when the
   workspace reloads. No half-written assistant message: a thread is persisted only on completion.
5. **Retry.** `POST /api/reviews/{id}/discuss` already accepts a one-element `threads` array
   (`DiscussRequest.threads`, `schemas/review.py:226`), so no endpoint is needed — the UI needs a
   **Retry** button on a failed card that re-sends that one draft, rather than requiring the
   draft to be retyped.
6. **UX.** Deltas render into the existing `CommentBox` with a caret; the card scrolls with the
   stream unless the reviewer has scrolled up; the footer shows "2 of 5 answered" instead of one
   indeterminate spinner.

**Touch points.** `services/llm_service.py` (streaming transports), `services/discussion.py`
(per-thread persistence + cancellation), `api/routes/reviews.py` (new SSE route with the existing
SSE headers), `frontend/src/services/api.ts` (a `streamDiscussion` reader, since `fetch` +
`ReadableStream` replaces the JSON client for this one call), `CommentBox.tsx`,
`StickyActionBar.tsx`, a new `hooks/useDiscussionStream.ts`.

**Risks.**

- **Three stream formats, one contract.** The largest surface for provider-specific bugs; test
  each with a recorded fixture, and keep the non-streaming path as the fallback when a provider
  cannot stream.
- **Proxy buffering.** `X-Accel-Buffering: no` and no compression on this route; the existing
  `/events` route already documents the SSE header set — reuse it verbatim.
- **Serverless limits.** Streaming works on Vercel but the function budget still applies; a very
  slow local model remains slow. Cancellation is the mitigation, not a longer timeout.
- **Partial-state correctness.** A cancelled submit must leave a consistent workspace: no
  orphan user message without a reply, no round advanced without text. The per-thread transaction
  is the guarantee — do not batch the writes and then stream.

**Verification.** Stubbed streaming generators per provider produce the same final text as the
blocking path; a test that aborts mid-stream leaves the completed thread persisted and the
unstarted thread untouched; a test that a `thread_error` for one thread does not abort the others;
manual: a local model streams visibly, the Stop button stops within a second, and Retry answers
one card.

---

## Deliberately not in the top five

Real gaps, deliberately deferred — cheapest first:

- **CI.** There is no `.github/` directory: `pytest -q`, `npm run build` and the Alembic
  up/down round-trip are all manual, though `AGENTS.md` §11 treats them as gates. A single
  workflow with a Postgres service container plus a scratch-database migration job would remove
  the "it passed on my machine" class of failure. S effort, no product change — this is the first
  thing to do if the next turn is not a feature.
- **Review management.** No `DELETE /api/reviews`, no pagination, no filter by repo/status/model,
  and `list_reviews` returns everything. S–M, no schema change.
- **Per-repository presets.** Every review re-picks foundation and model by hand. Remembering
  `(repo → foundation, model, verdict default)` on the last review for that repo would remove a
  dropdown from the most repeated action. S–M, one column or small table.
- **Skill authoring in the UI.** The Skills page uploads, creates and deletes but cannot edit a
  file, diff versions, or dry-run a foundation against a sample diff. Phase 21 (S3 storage) is
  still design-only, which also blocks uploads on Vercel. M–L.
- **Password reset and email verification.** Phase 12 put both out of scope; acceptable for
  localhost, not for a shared Vercel deployment where a forgotten password is unrecoverable
  without database access. M.
- **Provider retry and fallback.** A single 429 or 502 from the chosen provider fails the whole
  ingest. Exponential backoff on 429/5xx and an optional "fallback to this key" setting would
  turn a dead review into a slow one. S–M.
- **Prompt-injection hardening.** The diff is untrusted input and is currently presented to the
  model as instructions-adjacent text. Delimiting it and testing that a malicious hunk cannot
  rewrite the output contract is cheap insurance. S, no schema change.

## Taking one forward

1. Pick an initiative and write `docs/plans/phase_<N>_plan.md` (next free `N`, derived with the
   numeric sort in `AGENTS.md` §1) using the mandated sections.
2. Resolve the open decision named in that initiative's entry before writing code.
3. Land it with the usual gates: `cd backend && pytest -q`, `npm run build` if the UI changed, and
   a schema round-trip if a migration was added.
4. Update `README.md`, `CHANGELOG.md` and this file — move the idea to a "Shipped" line with the
   phase that delivered it.
