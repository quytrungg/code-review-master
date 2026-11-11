# Review flow — ingest, progress, rounds, sync, publishing

Applies to everything under `backend/`. This is the product contract the whole app is built around;
root `AGENTS.md` §5 only points here.

## Ingest is a job

`POST /api/reviews` validates cheaply and returns `202`; the work runs in the background and streams
stages over `/events`. An exception the pipeline does not expect (a DB error, a bug in an importer)
is caught at the `run_ingest` boundary, rolled back, logged with its traceback, stored as `failed`
with the exception's first line only, and published as a terminal `error`. A review must never stay
`running`.

## Progress is a table, not memory

- Stages are rows in `review_events`. `progress.publish` owns a short session and never raises;
  `subscribe` polls `seq > last` every 0.5 s and yields `None` for the keep-alive. A late client
  replays from `seq=1`, and `MAX_EVENTS_PER_REVIEW = 200` prunes old rows on insert.
- Locally the ingest job is an `asyncio` task. In serverless mode it is a Starlette **background
  task**, because `asyncio.create_task` dies with the response. The `vercel` SDK is not a dependency
  (it needs pydantic ≥2.12).

## A large diff is reviewed in parts, never truncated

`review_units.plan_units` is the only decision point: a diff whose rendered files fit
`diff_max_chars` is **one** call (its own verdict is the review's), and anything past that is packed
into parts of whole files of at most `review_unit_chars`, at most `llm_review_concurrency` in
flight. Never split a file; a file larger than a part gets a part of its own and loses whole hunks
from the end, with the count stated in the prompt and in `code_reviews.notes`. A first hunk that
alone overflows is cut mid-hunk (nothing else could be shown) and reported the same way.

Each part is a normal `ingest` call: same system prompt, `part i of n` in the user prompt, its own
`llm_calls` row. Anchoring stays global — every finding is anchored against the full parsed diff,
so a part can never introduce an anchor the diff does not have. After anchoring: dedupe per
`(path, line)` keeping the longest body, then cap at `review_max_findings` by severity. A review
with more than one part gets one extra `verdict` call over the merged findings, because no part saw
the whole change; if it fails, the opinion stays empty and the review is still `draft`.

Partial failure is not a failed review: the parts that landed are published as `draft` with one note
per failed part naming the files it did not cover. Every part failing is a failed review, exactly as
a single failed call always was.

## A watch reviews the delta it already fetched

`watch_service.tick` is the only caller of `vcs.compare`. Per enabled watch it fetches the PR head,
and — when it moved — claims the delta with a compare-and-set `UPDATE … WHERE last_seen_commit_id =
<old>` issued in the same transaction as `create_running_review`, so two ticks cannot both insert a
review (`UNIQUE(watch_id, commit_id)` is the second guard). It then hands `execute` the PR and the
`compare(old…new)` diff it already has: a delta review must never refetch the whole change, and the
one place that still reads the full diff is apply's anchor re-validation, which is correct because a
delta's lines are a subset of the pull request's.

`last_seen_commit_id` advances at creation, not at success: a failed delta review is visible as
`failed`, the watch keeps moving with later pushes, and the operator can re-run that URL by hand.
A watch with no base (`NULL`, e.g. created from a review that never fetched) adopts the current head
on its first check instead of reviewing the whole PR by accident.

The scheduler is the deployment's, not the service's: locally the lifespan starts an asyncio loop
(never when `SERVERLESS=true` or `WATCH_INTERVAL_MINUTES=0`); serverless uses
`POST /api/watches/tick` from `vercel.json`'s cron, which runs its reviews inline so they survive the
response. A tick never holds a transaction across the ingest: the review row is committed first, then
`run_ingest` opens its own session like any other ingest.

## Startup differs by mode

- Local and Docker: `init_db()` (alembic upgrade head) and `fail_orphaned_reviews()` at startup —
  one long-lived process owns every job, so a leftover `running` row cannot finish.
- `SERVERLESS=true`: neither. Migrations are a release step, and another instance may own the
  review. Reads call `mark_stale_running_reviews()` (10 minutes > `maxDuration`), which fails the row
  and publishes a terminal event. Never run `fail_orphaned_reviews()` where instances share a DB.

## Anchoring is mandatory

Store a finding only if it maps to a real RIGHT-side diff line, and rebuild the stored `diffHunk`
from hunk context — never the model's quote. Re-validate anchors at apply time. On GitHub a rejected
review is a `502`; there is no retry (the body-only retry disappeared with the review body).

## Threads are one kind, with rounds

- `origin` is `AI_GENERATED` or `GITHUB_EXISTING`; `github_root_comment_id` is the PR thread id (set
  at ingest for imported threads, backfilled from the review's comments after the first apply for
  AI ones).
- Every inbound comment opens a `ThreadRound`: `drafting` → `pending_apply` → `published` or
  `resolved_no_reply`. Discussing a closed round opens a new one. An imported round 1 is `published`
  because it already exists on GitHub; an AI round 1 is `drafting` (undecided) and is not published
  until the reviewer accepts it.
- Two decisions, and only an accepted round can be published: **accept** (`pending_apply`; one
  round-scoped model pass writes the GitHub comment, and the reviewer may save their own wording)
  and **push back** (`resolved_no_reply`, plus `dropped` on an AI round 1). `publish`/`resolve` are
  aliases. Apply posts the accepted text and never rewrites it; only a thread without accepted text
  falls back to the summarise-and-collate pass.

## Discussion has two transports

`POST /discuss` (JSON) answers everything behind one gather and keeps the reviewer's message even
when the model fails; `POST /discuss/stream` (SSE) streams per-thread deltas and writes each
thread's user + assistant messages **atomically on completion** — a failed or client-aborted
thread persists nothing, the draft stays client-side, and `done` is never sent on abort. Both
share `discussion.prepare_discussion`, which appends the incoming question to the prompt as a
transient tail because the streaming path may never persist it.

## Sync is idempotent by comment id

`thread_sync.known_comment_ids` covers roots, round inbound and published ids, and
`thread_messages.github_comment_id`. Identity is never the author: the operator replies from the
same GitHub account the token uses, so a comment is this review's own only when its
`pull_request_review_id` matches the id in the review's `github_review_url`. Sync heals AI threads
whose root id was never stored by matching the posted text. Apply posts only `pending_apply` rounds;
an apply with nothing pending is a `409`. Imported discussions and replies are GitHub-only.

## Publishing is inline comments only

The review is created with no `body`; the comments carry the findings. Nothing to publish is an error
(`422` when pruning leaves nothing, `502` when GitHub rejects), never an empty review, and dropped
threads are never posted. One exception: an `APPROVE` with nothing pending is an approval with no
comments — the PR is the whole message, and `COMMENT`/`REQUEST_CHANGES` keep the error. The AI opinion
is refreshed after each discussion submit; a failed pass keeps the previous verdict and warns.
