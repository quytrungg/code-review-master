# Phase 23 — Approve a pull request with nothing to publish

## Objective & Scope

**In:** A reviewer can submit an `APPROVE` review when there is no accepted finding and no queued
reply. The review goes out as an approval with zero inline comments — the same thing the GitHub
"Approve" button does. Pending work keeps working exactly as it does today.

**Out:**

- No new endpoint, no new column, no Alembic revision.
- `COMMENT` and `REQUEST_CHANGES` with nothing pending stay a `400`: an empty comment review is
  noise on the PR, and GitHub's web UI does not offer one either.
- Pruning is unchanged. If findings were accepted and every anchor turned out stale, the apply is
  still a `422` — the reviewer is told the findings no longer apply rather than silently approving.
- No review body is added. "Approve with a note" is a different feature.

## High-Level Design

```mermaid
flowchart TD
    A[POST /reviews/:id/apply] --> B{accepted findings<br/>or queued replies?}
    B -->|yes| C[build + revalidate comments]
    C --> D{comments left?}
    D -->|no| E[422 — nothing to publish]
    D -->|yes| F[publish review with comments]
    B -->|no| G{event == APPROVE?}
    G -->|no| H[400/409 — nothing accepted]
    G -->|yes| I{review already applied?}
    I -->|yes| H
    I -->|no| J[publish review with comments=[]]
    F --> K[mark rounds + review applied]
    J --> K
```

The empty-approval branch reuses `vcs.publish`, so GitHub posts
`POST /repos/{repo}/pulls/{n}/reviews` with `{"commit_id", "event": "APPROVE", "comments": []}` and
GitLab posts no discussions and calls its approval endpoint. `pull_request_review` events on GitHub
accept an approval with no body and no comments (this is what the web UI sends); a rejection comes
back as the existing `502` with GitHub's message.

## API Contracts & Schema

No schema change; `alembic_version` stays at head. `ApplyRequest` / `ApplyResponse` are unchanged.

Request — the only new accepted shape:

```json
{ "event": "APPROVE" }
```

Response `200`:

```json
{
  "review": { "id": 7, "status": "applied", "verdict": "APPROVE", "...": "unchanged" },
  "github_review_url": "https://github.com/octo/example/pull/123#pullrequestreview-9",
  "comments_posted": 0,
  "replies_posted": 0,
  "summarised": false,
  "dropped": [],
  "warnings": []
}
```

Status codes after the change:

| case | before | after |
| --- | --- | --- |
| `APPROVE`, nothing pending, review not applied | `400` | `200`, empty approval |
| `COMMENT` / `REQUEST_CHANGES`, nothing pending | `400` | `400` (unchanged) |
| nothing pending, review already applied | `409` | `409` (unchanged) |
| accepted findings all pruned by anchor re-validation | `422` | `422` (unchanged) |

## Target File Map

| File | Change |
| --- | --- |
| `backend/app/services/apply_service.py` | `approval_only` branch; publish moved out of `if initial:` so both paths share it. |
| `backend/tests/test_apply.py` | Empty approval, refusal stays for `COMMENT`, second empty approval is `409`. |
| `backend/tests/test_gitlab_service.py` | Empty approval still calls GitLab `approve`. |
| `frontend/src/components/StickyActionBar.tsx` | `allowEmptyApply` prop; Apply no longer requires `applyCount > 0`. |
| `frontend/src/pages/ReviewDetailPage.tsx` | Compute the empty-approval case, its label and disabled reason. |
| `backend/rules/review-flow.md` | Record the approval-only exception to "inline comments only". |
| `README.md` | Apply section, API reference, footer description. |
| `CHANGELOG.md` | Phase 23 entry. |
| `docs/plans/phase_23_plan.md` | This file. |

Left alone: `vcs.py`, `github_service.py`, `gitlab_service.py`, `discussion.py`, `summarise.py`,
models, schemas, migrations.

## Ordered Steps

1. `apply_review`: compute `approval_only = payload.event == "APPROVE"`; when nothing is pending and
   the review is not already applied, fall through to publishing instead of raising `400`
   (still `400` for the other two events).
2. Hoist the `vcs.publish` + status bookkeeping out of `if initial:` into `if initial or approval_only:`
   so comments and the empty case share one call; the backfill and round-marking loops stay guarded
   by `if initial:`.
3. Frontend: `allowEmptyApply` on the sticky bar, and in `ReviewDetailPage` enable Apply with the
   label "Approve on GitHub" when `pending.total === 0 && verdict === "APPROVE" && status !== "applied"`.
4. Tests for both providers and both directions (approve allowed, comment still refused).
5. Update `review-flow.md`, README and CHANGELOG.
6. Run `cd backend && pytest -q` and `cd frontend && npm run build`.

## Verification

- `pytest -q`: **223 passed, 1 failed**. The one failure is
  `test_serverless_mode.py::test_local_ollama_is_hidden_and_rejected` and is pre-existing and
  unrelated: `app/api/routes/models.py` compares `key.provider` against `llm_service.OLLAMA_LOCAL`
  (`"ollama-local"`, the model-id prefix) while the stored provider id is `"ollama_local"`
  (`app/models/keys.py`), so the serverless hide never matches. That file is unmodified in this
  change; the fix is one line and belongs in its own change.
- The four new apply tests cover: empty approval posts `comments: []` and stores the URL and
  verdict; the findings stay `drafting`; `COMMENT` with nothing pending is still `400`; a second
  empty approval is `409`; and an `APPROVE` whose only pending work is a queued reply posts the
  reply and no review, which is the behaviour that existed before this change.
  `tests/test_gitlab_service.py` covers the GitLab empty approval.
- `npm run build` green.
- Not exercised live against a real pull request: every review in the operator's database points at
  a real PR, and publishing one is the side effect this change is about. The HTTP-level tests drive
  the real app, routes, migrations and database with the provider stubbed at the service boundary,
  which is the evidence standard `AGENTS.md` §8 sets.
