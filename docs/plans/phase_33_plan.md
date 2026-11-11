# Phase 33 — Streaming discussion replies, per-thread retry and cancel

Implements `INITIATIVES.md` initiative 5. Named phase 33 because `phase_32_plan.md` (inbox
model/skill picker) already exists as in-flight work by another change; this phase does not
touch its files (`InboxPage.tsx`, `StartReviewModal.tsx`, its CHANGELOG entry).

> Correction to the initiative's evidence: `README.md` has no "No streaming" limitation to
> remove (that line predates the README rewrite); this phase adds a highlight line instead.
> It also states `DiscussRequest.threads` is at `schemas/review.py:226`; it is at line 247 —
> the one-element retry payload was already supported, so no endpoint change is needed for
> retry, only UI.

## 1. Objective & Scope

`POST /api/reviews/{id}/discuss` answers every drafted thread behind one `asyncio.gather` and
returns when the slowest call finishes; the UI shows a per-card "Thinking…" badge for the whole
wait. On a slow local model that is a minute or more of silence, one thread's failure is only
visible at the end, and there is no way to stop a submit or retry one thread without retyping.

This phase adds a streaming discussion endpoint and wires the workspace to it:

- `POST /api/reviews/{id}/discuss/stream` — Server-Sent Events: one `thread_started` per
  thread, `delta` text chunks as the model types, `thread_done` / `thread_error` per thread, and
  a terminal `done` with counts and the opinion-refresh result.
- Provider streaming in `llm_service.stream()`: Anthropic SSE via the SDK's `messages.stream`,
  OpenAI `stream=true` + `stream_options.include_usage`, Ollama NDJSON — all recorded in the
  `llm_calls` ledger with the same `LLMResult` shape as `generate()`.
- **Per-thread atomic persistence**: a thread's user + assistant messages are written together
  in one short transaction when its answer completes (and the review flips `draft →
  in_discussion`). A failed or cancelled thread writes nothing — no orphan user message, no
  round advanced without text. This intentionally differs from the JSON path, which persists
  the reviewer's message eagerly even when the model fails; that path keeps the existing
  behaviour and tests untouched.
- **Cancel**: a Stop button aborts the fetch; the server cancels the in-flight provider calls;
  threads that already completed stay persisted and appear on reload.
- **Retry**: a failed card shows a Retry button that resubmits that one draft through the same
  stream.
- **Progress UX**: deltas render live in a streaming bubble inside the existing `CommentBox`
  with a caret; the card tail-scrolls unless the reviewer scrolled up; the footer shows
  "N of M answered" instead of one spinner for the whole batch.

**Out of scope**

- Changing the JSON `POST /discuss` endpoint's wire contract or its eager user-message
  persistence (compatibility + existing tests).
- Streaming ingest or verdict passes; only discussion answers stream.
- Token-level retry/backoff or provider fallback (a separate backlog idea).
- Any schema change or config addition — none is needed.

## 2. High-Level Design

```mermaid
sequenceDiagram
    participant UI as Workspace (useDiscussionStream)
    participant API as POST /reviews/{id}/discuss/stream
    participant SVC as discussion.stream_discussion
    participant LLM as llm_service.stream
    participant DB as SessionLocal per thread

    UI->>API: threads [{thread_id, message}...]
    API->>SVC: prepare (validate, credentials, prompts) — errors are 4xx JSON, before streaming
    API-->>UI: 200 text/event-stream
    SVC->>LLM: one streaming task per thread
    par per thread
        LLM-->>SVC: on_delta(chunk)
        SVC-->>UI: event: delta {thread_id, text}
        LLM-->>SVC: LLMResult (usage → llm_calls)
        SVC->>DB: user msg + assistant msg, draft→in_discussion, commit
        SVC-->>UI: event: thread_done {thread_id, message_id}
    end
    SVC->>LLM: verdict re-evaluation (generate, as today)
    SVC-->>UI: event: done {answered, failed, opinion_refreshed, warnings}
    UI->>API: GET /reviews/{id} (fresh state)

    Note over UI,DB: Client abort → fetch abort → generator torn down → tasks cancelled.<br/>Already-committed threads stay; in-flight threads write nothing.
```

One queue fans the per-thread events into the single response stream; each thread task owns its
persistence transaction, which is what makes cancel and partial failure correct.

## 3. API Contracts & Schema

No schema change, **no Alembic revision**. One new endpoint; the JSON endpoint is unchanged.

### `POST /api/reviews/{review_id}/discuss/stream`

Request body: identical to `/discuss` — `DiscussRequest { threads: [{thread_id, message}] }`
(1–20 threads, message 1–4000 chars).

Pre-stream failures are plain JSON errors, exactly as the JSON endpoint: `404` unknown review,
`400` foreign `thread_id`, `422` bad model id / missing key detail. The client must check
`response.ok` before reading the stream.

On success: `200`, `Content-Type: text/event-stream`, headers `Cache-Control: no-cache`,
`Connection: keep-alive`, `X-Accel-Buffering: no` (the existing `SSE_HEADERS` set, verbatim).
Named events, one JSON `data:` line each:

```text
event: thread_started
data: {"thread_id": 12}

event: delta
data: {"thread_id": 12, "text": "You are"}

event: thread_done
data: {"thread_id": 12, "message_id": 403, "references": []}

event: thread_error
data: {"thread_id": 13, "error": "Ollama returned HTTP 404: ...", "references": []}

event: done
data: {"answered": 1, "failed": 1, "opinion_refreshed": true, "warnings": []}
```

- `thread_started` fires before the provider call for that thread (all threads start, subject
  to event-loop scheduling).
- `delta` carries raw text chunks, in order, per thread; chunks of different threads may
  interleave. The client concatenates per `thread_id`.
- `thread_done.message_id` is the persisted assistant `ThreadMessage.id`; the exchange is
  already committed when this event is sent.
- `thread_error.error` is the provider/validation message, same text the JSON path returns in
  `DiscussResult.error`. The thread's draft is not persisted.
- `done` is terminal and always sent when the server finishes normally — including when every
  thread failed. It is **not** sent on client abort. The review body itself is not embedded;
  the UI refetches with `GET /reviews/{id}`, which is one request it already knows how to make.

## 4. Target File Map

**Backend**

- `backend/app/services/llm_service.py` — **changed**: `stream()` wrapper (endpoint
  resolution, ledger record on success and failure, same `LLMResult`) plus `_stream_ollama`,
  `_stream_openai`, `_stream_claude` adapters; `on_delta` is a plain `Callable[[str], None]`.
- `backend/app/services/discussion.py` — **changed**: extract `prepare_discussion()` (shared
  validation/credentials/prompts, used by the existing JSON path too) and
  `_refresh_opinion()`; add `stream_discussion()` async generator and `_persist_exchange()`
  (per-thread atomic write). `discuss_threads()` behaviour is untouched.
- `backend/app/api/routes/reviews.py` — **changed**: `POST /{review_id}/discuss/stream`
  returning `StreamingResponse` with `SSE_HEADERS`.
- `backend/tests/test_llm_stream.py` — **new**: adapter parity tests (streamed text ==
  blocking text, usage parsed, failures recorded and raised).
- `backend/tests/test_discussion_stream.py` — **new**: endpoint SSE contract, partial failure,
  cancel-at-service-level, guards.

**Frontend**

- `frontend/src/types/index.ts` — **changed**: `DiscussionStreamEvent` union.
- `frontend/src/services/api.ts` — **changed**: `streamDiscussion()` (fetch + ReadableStream
  SSE parser, `AbortSignal` support, same error shape as `request()` for pre-stream failures).
- `frontend/src/hooks/useDiscussionStream.ts` — **new**: stream lifecycle, per-thread state
  (`sending`/`done`/`error` + accumulated text), `stop()`, `doneInfo`.
- `frontend/src/components/CommentBox.tsx` — **changed**: streaming bubble with caret and
  tail-scroll; Retry button on a failed card.
- `frontend/src/components/StickyActionBar.tsx` — **changed**: "N of M answered" label and Stop
  button while streaming.
- `frontend/src/pages/ReviewDetailPage.tsx` — **changed**: `submitDrafts` drives the hook;
  `doneInfo` triggers refetch, draft clearing, per-thread errors and the summary notice; passes
  stream state into the cards and Stop into the bar.

**Docs**

- `docs/plans/phase_33_plan.md` (this file), `CHANGELOG.md`, `README.md` (one highlight line),
  `INITIATIVES.md` (initiative 5 → shipped), `backend/rules/review-flow.md` (one line on the
  streaming persistence rule).

**Left alone**: the in-flight phase 32 files (`InboxPage.tsx`, `StartReviewModal.tsx`, their
CHANGELOG hunk), `IngestProgress.tsx`, all watch/analytics/apply code.

## 5. Ordered Steps

1. `llm_service.stream()` + three adapters (Ollama NDJSON, OpenAI SSE, Claude SDK stream).
   `on_delta` is sync; adapters assemble the full text and return the same `LLMResult` as the
   blocking calls, with usage from the terminal frame (`claude_usage`/`openai_usage` /
   `ollama_usage` already handle streamed shapes). Failure mirrors `generate()`: record
   `ok=False` in the ledger, then raise. `asyncio.CancelledError` propagates unrecorded —
   a cancelled call's usage is unknowable.
2. `discussion.py`: `prepare_discussion(db, review, entries)` returns a detached
   `PreparedDiscussion` (credentials, model, system prompt, per-entry user prompts and
   reference ordinals, review id); re-point `discuss_threads` at it without behaviour change.
   Add `_persist_exchange(review_id, thread_id, user_text, assistant_text)` (fresh
   `SessionLocal`, `open_scratchpad_round`, both messages, status flip, commit; returns the
   assistant message id) and `stream_discussion(prepared)`:
   one `asyncio` task per entry pushing `thread_started`/`delta`/`thread_done`/`thread_error`
   events onto one `asyncio.Queue`; the generator drains the queue until all tasks ended, then
   runs `_refresh_opinion` with a fresh session and yields `done`; `finally:` cancels and
   gathers any surviving tasks (that is the cancel path).
3. Route: validate + prepare (JSON errors before streaming), then `StreamingResponse`.
4. Backend tests (§6); `cd backend && pytest -q`.
5. Frontend: types → `api.streamDiscussion` → hook → `CommentBox` (bubble, caret,
   tail-scroll, Retry) → `StickyActionBar` (progress label, Stop) → `ReviewDetailPage`
   wiring. `npm run build`.
6. Live verification: mock GitHub + Ollama (scratch copy of the mock extended to stream NDJSON
   when `stream: true`), backend on a scratch port with a temp SQLite database, Vite dev
   server, drive the workspace in a real browser: multi-thread submit with visible deltas,
   "N of M answered", Stop mid-stream (reload shows only the completed thread persisted),
   Retry on a forced 404 model (error card) that then succeeds.
7. Docs (README, CHANGELOG, INITIATIVES, review-flow.md).

## 6. Verification

**Backend tests** (`backend/tests/test_llm_stream.py`, `test_discussion_stream.py`):

- `_stream_ollama` and `_stream_openai` against `httpx.MockTransport` serving recorded
  NDJSON / SSE bytes: concatenated deltas equal the blocking response text; usage parsed from
  the terminal frame; an HTTP error raises `LLMError` and is ledger-recorded with `ok=False`.
- `_stream_claude` against a fake `AsyncAnthropic` (monkeypatched on the `anthropic` module):
  text and usage merge match `claude_usage`'s streamed-event contract.
- Endpoint: `client.stream("POST", .../discuss/stream)` with stubbed `llm_service.stream` and
  `llm_service.generate` (verdict) — assert the event order (`thread_started` → `delta`* →
  `thread_done` for both threads, terminal `done`), then `GET` the review: each thread has
  `[ai, user, assistant]` and the status is `in_discussion`.
- Partial failure: one stream stub raises → `thread_error`, the other thread fully persisted,
  the failed thread has **no** new messages (the streaming rule), `done` reports
  `answered=1, failed=1`.
- Cancel: call `stream_discussion` directly under `asyncio.run`, one stub completing and one
  stub hanging; consume until the first `thread_done`, then `aclose()`; assert the completed
  exchange is persisted, the hanging thread wrote nothing, and no task is left pending.
- Guards: unknown review → 404, foreign thread id → 400, before any SSE body.
- Gates: `cd backend && pytest -q`; if frontend changed, `cd frontend && npm run build`.

## 7. Execution record

Executed 2026-11-11, in parallel with another session's in-flight phase 32 work (untouched).

- `cd backend && pytest -q` → **307 passed** (10 new: 4 adapter/wrapper tests in
  `test_llm_stream.py`, 6 endpoint/service tests in `test_discussion_stream.py`), including the
  cancel test asserting the completed exchange persists, the hung thread writes nothing, and no
  task is left pending.
- `cd frontend && npm run build` (`tsc -b` + vite) → **green**.
- Live run: backend on :8011 with a throwaway SQLite DB, mock GitHub + Ollama on :9011 (NDJSON
  streaming), real browser on the served SPA, throwaway account. Observed:
  - 3-thread submit → 3 `stream=true` chat calls + 1 verdict call in the mock log; all threads
    persisted `[assistant, user, assistant]`; notice "3 replies added · AI opinion updated";
    header usage line "5 calls · 2.4k tokens".
  - Mid-flight: footer "0 of 2 answered" + Stop; both cards in the "answering…" bubble state.
  - Forced 500 on one stream → card error "Ollama returned HTTP 500: mock forced failure" with a
    Retry button; the failed thread persisted nothing new; notice "1 failed (draft kept)".
  - Retry clicked → one `stream=true` call, "1 reply added · AI opinion updated", thread
    round 2 committed as `[user, assistant]`.
  - Stop at ~350ms on a 2-thread submit → both cards "Stopped before the reply arrived — retry
    when ready." with Retry; reload showed both threads unchanged (no orphan user messages); the
    mock logged BrokenPipe on its writes, proving the backend cancelled the upstream calls.
  - Final state: threads at 7/5/9 messages, `in_discussion`, verdict COMMENT 70%.
- Cleanup: mock and backend processes stopped; the throwaway DB and mock live in the scratch
  dir and expire there.
