# Phase 31 — Inbox: authored and assigned PRs

## 1. Objective & Scope

Widen inbox discovery so the queue also shows open PRs **authored by** or **assigned to** the
authenticated user, and tag each row with an `involvement` role (`reviewer` / `assignee` /
`author`) so the UI can tell "a review request" apart from "your own PR" and "assigned to you".

**In scope**

- Two new discovery queries: `is:pr is:open author:{login} archived:false` and
  `is:pr is:open assignee:{login} archived:false`, deduped with the existing three.
- `cached_prs.involvement` (migration `0016_inbox_involvement`), computed at sync from the search
  item: author beats assignee beats reviewer.
- Turn-taking semantics unchanged and now double-duty: on an authored PR, a reply after your last
  action re-arms the row to `needs_review` with an unread count — i.e. "your PR needs attention".
- UI: a `Your PR` / `Assigned` badge on the card.
- **Link on creation, not sync** (added after first ship): `create_running_review` stamps
  `linked_review_id` on any cached row for the PR the moment a review starts — manual or
  watch-triggered — so the card flips from "AI review" to "Open review" without a GitHub sync.

**Out of scope**

- Filtering or de-prioritising these rows (no new filter), changing the commenter sweep, or any
  team allowlist — the operator explicitly declined those earlier.
- A separate nav/section for own PRs; they share the inbox list, distinguished by the badge.

## 2. High-Level Design

```mermaid
flowchart LR
    Q1[review-requested:login] --> M((merge, dedupe by PR URL))
    Q2[team-review-requested:org/slug × teams] --> M
    Q3[commenter:login] --> M
    Q4[author:login] --> M
    Q5[assignee:login] --> M
    M --> R[per-PR status + turn-taking]
    R --> I[involvement = author | assignee | reviewer]
    I --> DB[(cached_prs)]
```

Authored PRs can never carry an own formal review (GitHub forbids self-review), so their base
status resolves to `needs_review` or `commented`, and any later reply flips them to
`needs_review` + unread — the same state machine as reviewers, read as "your turn to respond".

## 3. API Contracts & Schema

Migration `0016_inbox_involvement` (revises `0015`), one column, no backfill semantics matter:

```python
with op.batch_alter_table("cached_prs") as batch:
    batch.add_column(
        sa.Column("involvement", sa.String(24), nullable=False, server_default="reviewer")
    )
```

`batch_alter_table` keeps SQLite (tests, local files) and PostgreSQL consistent. Existing rows are
`reviewer` until their next sync recomputes the role — correct for every row that only the three
legacy queries could have discovered.

`CachedPRRead` gains `involvement: str` (default `"reviewer"`); frontend type gains
`CachedPRInvolvement = "reviewer" | "author" | "assignee"`. No other contract changes; no new
routes.

## 4. Target File Map

- `backend/alembic/versions/0016_inbox_involvement.py` — the column (up/down verified).
- `backend/app/models/cached_pr.py` — `involvement` column + `InboxInvolvement` constants.
- `backend/app/services/github_inbox_service.py` — the two queries and role computation.
- `backend/app/schemas/inbox.py` — expose `involvement`.
- `backend/tests/test_inbox.py` — authored/assigned discovery, role values, re-arm on own PR.
- `frontend/src/types/index.ts`, `frontend/src/pages/InboxPage.tsx` — type and badge.
- `CHANGELOG.md` — the entry; this plan.

## 5. Ordered Steps

1. Plan (this file), migration 0016, round-trip on a scratch DB.
2. Model + service + schema change.
3. Tests extend `test_inbox.py`; full `pytest -q` green.
4. Frontend type + badge; `npm run build` green.
5. CHANGELOG entry and executed evidence appended here.

## 6. Verification

- Scratch round trip: 0016 applies down and up cleanly.
- `pytest -q` green, including: a sync with an authored and an assigned item carries both,
  `involvement` is `author`/`assignee`/`reviewer` as appropriate, an own PR with later replies
  re-arms to `needs_review` with the right unread count, and an authored PR that also matches the
  reviewer queries dedupes to one row tagged `author`.
- `npm run build` green.

### Executed evidence (2026-11-11)

- `pytest -q` — **297 passed** (4 new: authored/assigned discovery with role values and both
  queries asserted, authored PR re-arming with unread replies, authored PR deduped across queries,
  and review creation linking the cached row without a sync).
- Scratch round trip: `0016` adds and `PRAGMA table_info` confirms `involvement`; `downgrade -1`
  drops it and returns `alembic_version` to `0015`; upgrade again OK.
- `npm run build` — clean.
