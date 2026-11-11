# INITIATIVES — what to build next

Last updated: 2026-11-11 · Covers phases 1–33 (phases 21–33 shipped or in flight since the last
update; initiative 5, streaming, was taken forward as phase 33).

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
| 5 | ~~Streaming replies, per-thread retry, cancel~~ | Shipped in phase 33 — see §5 for the deviations | L | no |
| 6 | ~~Learn my standards: push-backs become skill rules~~ | Shipped in phase 36 — see §6 for the deviations (beta-gated by phase 35) | M | yes |
| 7 | Deterministic pre-pass checks before the model | Secret and hygiene catches with zero tokens | S–M | no |
| 8 | Standing review policies on the inbox | The queue stops needing clicks to move | M–L | yes |
| 9 | Cross-review finding search and recurring issues | "We have flagged this three times before" | M | yes |
| 10 | Side-by-side model comparison | Answers the folklore question with data | M | no |

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

## 5. Streaming replies, per-thread retry and cancel — shipped, phase 33

> Built as `docs/plans/phase_33_plan.md`. Deviations from the sketch below: the README line "No
> streaming" no longer existed (the evidence was stale; the README gained a highlight sentence
> instead); the terminal `done` event carries counts plus the opinion-refresh flag and the UI
> refetches the review rather than receiving it embedded; and `llm_service.stream()` on_delta is a
> plain callback, not a generator, so cancellation propagates as an ordinary coroutine cancel.
> The per-thread persistence rule landed exactly as sketched — user + assistant messages commit
> together only when the answer completes — which meant the discussion prompt had to learn to
> include a question that may never be persisted (a transient transcript tail in
> `prepare_discussion`). Verified end to end against a streaming Ollama mock: a 3-thread submit
> issued 3 `stream=true` chat calls plus one verdict call; the footer read "0 of 2 answered" with
> a working Stop mid-flight; a forced 500 produced a `thread_error` card with a working Retry; a
> Stop at ~350ms persisted nothing for either thread (reload showed no orphan user messages).


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

---

## 6. Learn my standards: turn push-backs into skill-library rules — shipped, phase 36

> Built as `docs/plans/phase_36_plan.md` behind phase 35's `push_back_lessons` beta flag, with the
> operator's revisions: no proposal queue, no decision columns — the question is asked inline at
> the push back. Deviations from the text below: `RoundPanel` needed no change (the page intercepts
> the decision), `LLMPurpose` gained `LESSON` for the ledger, and the lesson service raises its own
> error type rather than importing `PipelineError` (import cycle).

**Problem.** The product's pitch is *"your standards, not generic advice"* — yet the standards only
ever flow one way. When a reviewer pushes back on a finding ("not a bug in this repo, we allow
bare `except:` in migrations"), that correction lives in `thread_messages.content` and dies when the
round is published. `thread_rounds` records status and published text but nothing structured about
*why* a finding was rejected (`backend/app/models/review.py`). The next PR from the same repo gets
the same false positive, because the skill library — the only place the model learns standards —
is maintained entirely by hand.

The raw material is already produced: push-backs are explicit decisions, the thread knows its
`file_path`, and ingest knows which skill files were selected for that file type. None of it is
captured.

**Proposal.** Revised 2026-11-11 after review, with two changes from the sketch above: the
proposal queue and the structured decision columns are gone — the question is asked inline at the
moment of the push back — and the whole feature is gated behind the phase 34 beta toggle, off by
default.

1. **Beta gate.** The flow exists only when the `push_back_lessons` beta flag is on (phase 34's
   settings section). Flag off, or flag unknown: Push back behaves exactly as today — no modal, no
   extra call.
2. **Modal on push back.** With the flag on, clicking Push back opens a modal *before* the round
   resolves: "Record the lesson from this push back in a skill foundation?" — **No** dismisses it
   and the push back proceeds exactly as today (publish nothing, withdraw the finding). **Yes**
   goes to step two.
3. **Pick a foundation, then apply.** Step two shows the skill-foundation picker (`GET /skills`)
   and a lesson title and body drafted by one small model call from the finding and its discussion
   — editable inline, because the reviewer, not the model, decides what the rule says. **Apply**
   writes the lesson into the chosen foundation as one markdown file and records attribution, then
   the push back proceeds. The file is written only on Apply — Cancel writes nothing.
4. **File naming for selection.** `skill_loader` scores files by path tokens (`_score`), so the
   lesson file must carry the finding's file type to ever be loaded again:
   `lessons/<filetype>-<slug>.md` (e.g. `lessons/python-n-plus-one-query.md`). A lesson that never
   reaches a future prompt is a diary entry, not a rule.
5. **Attribution.** A `skill_lessons` row (`thread_id`, `foundation`, `path`, `title`, `created_at`)
   links the rule back to the finding that produced it — "lesson recorded" on the thread, and the
   file header cites the review and thread.
6. **Serverless fallback.** Skill writes are disabled when `SERVERLESS=true`
   (`skills_service.require_writable`); there the Apply step becomes copy-to-clipboard with the
   markdown body, and no attribution row is written (nothing was applied).

**Touch points.** Phase 34's beta flag (`settings.beta_features`, `settings_service.beta_enabled`);
migration `0018_skill_lessons` (attribution table only — no decision columns, no proposals);
new `services/lessons_service.py` (draft + write, reusing `skills_service.save_skill_file`);
`api/routes/reviews.py` (lesson draft + apply endpoints, flag-checked);
`apply_service.decide_round` (nothing — the lesson lands before the decision is sent); frontend:
new `PushBackLessonModal.tsx`, wiring in `RoundPanel.tsx` + `ReviewDetailPage.tsx`, `api.ts`,
`types/index.ts`, `SettingsPage.tsx` (nothing — phase 34 owns the toggle).

**Risks.**

- **Rule quality.** A model-drafted rule is a finding about a finding; it must state scope (file
  type, path pattern) or it will over-suppress. The draft prompt demands the scope line, and the
  reviewer can edit before applying.
- **Scope creep of the flag.** This is the first beta feature; the gate must stay a plain boolean
  read at the call site, not grow a config system. One flag, one feature.
- **Privacy.** The draft call sends the finding plus the discussion to the provider — the same data
  the discussion already sent, so no new exposure; the stored lesson is the reviewer-approved text
  only.

**Verification.** Flag off: Push back resolves the round with no modal and no LLM call. Flag on,
"No": identical round outcome to today. Flag on, "Yes" → foundation picked → Apply: the foundation
contains `lessons/<filetype>-<slug>.md`, the `skill_lessons` row cites the thread, and the *next*
review's loaded bundle includes the lesson (assert on the built prompt). Cancel writes no file.
Another account's thread is a `404`, never a `403`. On serverless, Apply offers clipboard copy and
writes nothing.

---

## 7. Deterministic pre-pass checks before the model

**Problem.** The model is the *only* analysis layer — every finding costs a call, and the things a
regex catches with absolute certainty are exactly where LLMs are weakest: an AWS key pasted into a
fixture, a `.env` diff, a conflict marker, a `console.log` left in, `.skip()` appended to a test.
There is no pattern service anywhere in `backend/app/services/` (verified: no gitleaks, regex or
pattern module), so a review can *cost tokens and still miss a literal secret* — the worst
quality-per-dollar outcome the product has.

These checks need zero tokens, run in milliseconds, and are explainable in one line, which makes
them the cheapest credibility the tool can buy.

**Proposal.**

1. **A check packs service** — config-driven regex packs shipped alongside the skill library:
   `secrets` (high-entropy strings, known key prefixes: `AKIA`, `ghp_`, `sk-`, `-----BEGIN PRIVATE
   KEY`), `hygiene` (conflict markers, debugger prints, `.skip()`/`.only` in tests, `TODO` before
   release-blocking tags), off by default, enabled per review or globally in settings.
2. **Run after `diff_parser`, before the model call** — over the same parsed hunks, findings
   anchored through the existing anchoring path, so they are first-class threads: discussable,
   acceptable, publishable like any finding. `origin` gains a `CHECK` value (`String(16)`, no
   migration) with a deterministic severity set by the pack.
3. **The prompt knows.** An ingestion note states "3 deterministic findings exist (2 secrets, 1
   hygiene)" so the model does not re-report the same line — mirrors how multi-pass announces
   truncation.
4. **No false-positive flooding.** A per-review cap per pack, and a finding-level "ignore this
   pattern for this repo" that feeds initiative 6's proposal queue — the two initiatives are
   natural companions.

**Touch points.** New `backend/app/services/checks_service.py` (pack definitions as data, not
code), `review_pipeline.py` (a stage between parse and model call), `services/progress.py` (one
row: "Deterministic checks: 2 secrets, 1 hygiene issue"), `core/config.py` (enabled packs, caps),
`ThreadOrigin` widening, frontend (nothing — findings already render; maybe a Badge for CHECK
origin), tests with a fixture diff containing one real-shaped key.

**Risks.**

- **False positives on test fixtures.** Key-shaped strings in test fixtures are legitimate; the
  pack must recognise `test`, `fixture`, `mock` path hints or accept a path-based allowlist.
- **Pack sprawl.** Regex packs want to grow into a lint engine. They must stay at "things a
  reviewer would block a PR for", not a style checker; the plan should name the cut-off.

**Verification.** A diff containing a `ghp_…` token produces one anchored CHECK finding with zero
`llm_calls` rows; the finding publishes to GitHub like a model finding; a pack disabled in settings
produces none; the ingestion note appears and the model does not duplicate the line.

---

## 8. Standing review policies on the inbox

**Problem.** The pieces now exist independently but refuse to compose. The inbox (phase 28/31)
discovers PRs waiting on the user; watches (phase 27) review *new pushes* — but only on PRs that
already have a review, and only after someone clicked. Every first review — the most repeated
action in the product — still needs a human to notice the row and click (phase 32 made the click
informative, not automatic). A PR can sit in `needs_review` for days while its author waits.

The gap is not detection (the inbox already finds them) or review creation (`create_running_review`
works and links the cached row at creation, phase 31) — it is a standing instruction connecting the
two.

**Proposal.**

1. **`review_policies`** — `id, user_id, repo_pattern (glob), involvement (reviewer|assignee|
   author|any), model, foundation, enabled, max_active, created_at`. One policy per intent; the
   model/foundation columns reuse exactly what the phase 32 picker collects.
2. **Evaluation on the existing ticks.** The watch loop (local/Docker) and the serverless
   `POST /api/watches/tick` both already wake up periodically; a policy evaluation runs on the same
   tick, against the cached inbox rows (no extra GitHub calls until a review starts). A matching PR
   with no `linked_review_id` gets a review created, which stamps the link and flips the row to
   "Open review" — all phase 31 machinery, reused verbatim.
3. **Guardrails.** `max_active` caps concurrent policy-started reviews per policy; a soft monthly
   ceiling ties into the phase 22 ledger (warn, never block, per its "no hard block" rule); a
   policy-started review is marked `trigger='policy'` so the UI can say "started automatically".
4. **Watch composition.** When a policy starts a review, offer (or auto-create, per plan decision)
   the watch on it — so the PR is covered for its whole life, first push to last.

**Design decision the phase plan must make.** Auto-create the watch with the policy, or leave
watching explicit? Auto-creation is the coherent default (a standing reviewer should follow
pushes) but doubles the quota cost per PR; the plan must state which and why.

**Touch points.** New `models/policy.py`, `services/policy_service.py`, `api/routes/policies.py`;
migration; `watch_service.py` tick (evaluation hook), `github_inbox_service.py` (nothing — reads
cache), `review_pipeline` (nothing — receives a request like any other), frontend: a Policies panel
on Settings or the inbox header, a `trigger` badge on review cards.

**Risks.**

- **Spend.** The first initiative that spends tokens without a human in the loop. `max_active`,
  the soft ceiling, and default-off are the controls; the analytics page must attribute
  policy-started spend clearly.
- **Races.** A policy tick and a manual click on the same PR: the manual path wins (the link is
  stamped at creation), the tick must check the link inside the same transaction that creates the
  review — the phase 27 `UNIQUE` lesson applies; reuse the pattern.
- **Review spam on broad patterns.** A `*` repo pattern with `involvement=author` could start
  reviews on the user's own PRs. Default the pattern to one explicit repo and make widening a
  deliberate act.

**Verification.** A fixture cached PR matching a policy gets one linked review on tick; a
non-matching repo gets none; a PR already linked is untouched; two ticks racing produce one review;
`max_active=1` with two matches queues the second rather than starting it; the ledger rows carry
`trigger='policy'`.

---

## 9. Cross-review finding search and recurring-issue memory

**Problem.** Every review is an island. Summaries, file paths and discussion text live in
`review_threads` and `thread_messages` per review, and `GET /api/reviews` is an unfiltered list —
there is no search anywhere in the backend (verified: no `ilike`/`LIKE`/FTS in the routes). So the
questions a reviewer actually has are unanswerable: *have we flagged this N+1 pattern in this repo
before?*, *does every PR from this team re-introduce the same race condition?*, *which previous
thread argued about this same `dataclass` choice?* The multi-pass merge (phase 26) already
normalises finding titles for dedup — but only within one review.

Six months of reviews is a corpus of the team's actual defects and disputes; the tool stores it and
reads none of it.

**Proposal.**

1. **Full-text index over findings** — thread `summary` + first AI message, keyed by review, repo,
   file path and date. SQLite FTS5 and Postgres `tsvector` both available, one dialect-switching
   migration; rebuild from existing rows (no backfill semantics beyond the index itself).
2. **`GET /api/findings/search?q=&repo=&path=&since=`** — scoped search behind the existing
   ownership rule (another account's rows are a `404`, never a `403`).
3. **"Seen before" panel on a finding.** On opening a thread, search its normalised title within
   the same repo: prior matches appear as links ("same pattern as review #8, thread #3 — accepted
   then"). The phase 26 normalisation is the key; without it every match is a literal-string
   accident.
4. **Recurring-issues digest.** Grouped by normalised title per repo, on the analytics page:
   "Top recurring findings — api client: 5 reviews, 12 findings". This is the first metric that
   says something about *the codebase*, not the model.

**Touch points.** Migration (FTS table + triggers, dialect-aware — the plan must show the
`upgrade`/`downgrade` round-trip on both engines), new `services/finding_search.py` +
`api/routes/findings.py`, `schemas/`, frontend: search box on the dashboard, "seen before" section
in the workspace's `CommentBox` area, recurring panel on `AnalyticsPage`.

**Risks.**

- **Two engines, one index.** FTS5 and `tsvector` differ in tokenisation and ranking; the plan must
  pick a lowest-common-denominator query (prefix match on normalised words) or accept
  engine-specific ranking. This is the initiative's main complexity and the plan must name the
  choice.
- **Noise.** Normalised-title grouping will merge siblings that are genuinely different. Match
  links are evidence, not assertions — copy must say "similar to", never "duplicate of".
- **Privacy.** Summaries already live in the database and never leave the machine; search adds no
  exposure. Index text stays out of any prompt.

**Verification.** The same finding text in two reviews in one repo matches and links; the same
text in another repo does not surface unless repo is unset; a reworded title with the same
normalised key matches; `upgrade head` + `downgrade -1` round-trips on both SQLite and Postgres
leaving no orphaned FTS rows; another account's finding is a 404.

---

## 10. Side-by-side model comparison

**Problem.** Phase 22 made model quality *measurable* (acceptance rate, push-back rate, latency,
cost per model) but only *passively* — the numbers accrue from whatever reviews happened to use
each model. "Which model should this team use?" is still folklore unless someone runs the same
reviews twice by hand. The tool is one deliberate step away from answering its own hardest
question with data: run the same diff through two models and see what each found.

**Proposal.**

1. **"Compare with…" on any review** (and optionally as a checkbox in the phase 32 inbox picker):
   creates a second review of the same PR with a chosen second model — `parent_review_id` and
   `trigger='comparison'`, the phase 27 link machinery reused, no new schema.
2. **A merge view, not two panels.** Findings from both reviews keyed by the anchor
   `(path, line)` + the phase 26 normalised title — the multi-pass merge logic, applied across
   reviews: *both*, *A only*, *B only*, with per-finding provenance badges. Discussion and apply
   flow through the primary review as today; the comparison review is pinned to the same
   `commit_id` so anchors are directly comparable.
3. **Ledger integration.** Both runs write `llm_calls` with distinct models; the analytics
   acceptance/push-back rates then compare the two models on *the same PRs*, which is the only
   comparison that means anything.
4. **Cost honesty.** The UI shows the estimated cost of the comparison run before it starts
   (phase 22 price table) — this is the product's most expensive button and must say so.

**Touch points.** `review_pipeline` (a `trigger` plumbed through creation, no re-fetch of the
diff — pin both reviews to the same `commit_id`), `api/routes/reviews.py` (`POST /{id}/compare`),
a comparison merge service (new, small — reuses the `review_units` dedupe helpers), frontend:
compare button in the workspace header + merge view panel, `types/index.ts`.

**Risks.**

- **Not a benchmark.** One PR compares two models on *one diff*; the value is the trend across
  many comparisons plus analytics, and the copy must never claim a winner from n=1.
- **Divergent anchoring.** Two models may report the same defect at neighbouring lines; the anchor
  key needs a small line-tolerance window, decided in the plan, or "both" undercounts.
- **Double spend.** Every comparison doubles ingest cost for that PR. Opt-in, priced up front, and
  the ledger attributes each half clearly.

**Verification.** Two stubbed models with disjoint findings over one diff produce a merge view with
three buckets and correct provenance; a shared finding at ±2 lines merges into *both*; both runs
appear in `llm_calls` with their models; the comparison review links back to the parent; the cost
estimate renders before start.

---

## Taking one forward

1. Pick an initiative and write `docs/plans/phase_<N>_plan.md` (next free `N`, derived with the
   numeric sort in `AGENTS.md` §1) using the mandated sections.
2. Resolve the open decision named in that initiative's entry before writing code.
3. Land it with the usual gates: `cd backend && pytest -q`, `npm run build` if the UI changed, and
   a schema round-trip if a migration was added.
4. Update `README.md`, `CHANGELOG.md` and this file — move the idea to a "Shipped" line with the
   phase that delivered it.
