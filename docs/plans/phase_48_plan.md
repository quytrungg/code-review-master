# Phase 48 — Evolve from local agent sessions behind a folder picker

## Objective & Scope

**In.**

- The Skills page's evolve control becomes a header button that opens a **start modal**; the
  full-width card in the page body goes away. The modal picks the foundation, the model, and now
  the **agent session source**.
- Three sources, one per local agent tool, chosen from the same modal:
  - `claude` — `~/.claude/projects/**/*.jsonl` (Claude Code transcripts),
  - `codex` — `~/.codex/sessions/**/*.jsonl` (Codex rollouts),
  - `hermes` — `~/.hermes/state.db` (`sessions` + `messages`, read-only).
- The previous 30 days of the chosen source are condensed into "correction exchanges" — a user turn
  that pushes back on the assistant and the assistant turn it answers — and added to the
  meta-analysis prompt next to the existing review history. Choosing no source keeps today's
  behaviour exactly.
- Review-history evidence is still read and still cited by review id. Session evidence is cited in
  the summary, with `evidenceReviewIds: []` because a CLI session has no review number.

**Out.** No new dependency, no transcription of every message (turns are excerpted and scored, like
thread scoring), no write to any agent's folder or database, no background job (the scan runs inside
the analyse request, which is already a long call), no change to apply/clone, and **no Alembic
revision** — the schema is untouched.

## High-Level Design

```mermaid
flowchart LR
  UI[Skills header button] -->|opens| M[Start modal<br/>foundation · model · session source]
  M -->|POST analyze-history {days, model, sessionSource}| R[skills route]
  R --> S[skill_analyzer_service.analyse]
  S --> H[aggregate_history<br/>reviews + pushbacks]
  S --> A[agent_sessions_service.summarise<br/>claude / codex / hermes]
  H --> P[build_meta_prompt]
  A --> P
  P --> L[one evolve LLM call]
  L --> W[classified proposals → workbench modal]
  G[GET /api/skills] -->|session_sources: available?| M
```

Scanning rules, all read-only:

| source | location | reader | default cap |
| --- | --- | --- | --- |
| claude | `~/.claude/projects` | JSONL, `type=user/assistant` lines, `message.content` text blocks | 300 newest files, 2 MB each |
| codex | `~/.codex/sessions` | JSONL, `response_item` → `payload.type=message` with `input_text`/`output_text` | 300 newest files, 2 MB each |
| hermes | `~/.hermes/state.db` | SQLite `mode=ro`, join `messages`→`sessions`, `role in (user, assistant)` | 4 000 message rows |

Only files whose mtime is inside the window are opened, the scan is capped, and each turn is
excerpted to 240 characters before scoring. Every source path is overridable
(`CLAUDE_SESSIONS_DIR`, `CODEX_SESSIONS_DIR`, `HERMES_STATE_DB`) so tests and Docker can point at a
fixture without touching the operator's home directory. A missing root is not an error: the source
is reported `available: false` in `GET /api/skills` and the UI disables it.

Correction scoring mirrors `_score_thread`: a user turn that contains push-back markers ("no",
"wrong", "actually", "instead", "don't", "still", "revert", …) scores one point per distinct marker
(capped at 5); exchanges are sorted by score then recency, and the top ones are rendered until
`agent_session_max_chars` (16 000) is reached. Two filters keep the evidence human: a session's first
user turn is skipped (it is the task handed over, and it is where a CLI writes role prompts), and
injected turns — `<system-reminder>` blocks, `<environment_context>`, `<skill>`, `<command-*>` and
other context tags, "The following is the Codex agent history", "Another Claude session sent a
message:" — are dropped before scoring.

## API Contracts & Schema

**No Alembic revision.** Settings are environment/config only; no model or column changes.

`GET /api/skills` gains one array (additive, old clients unaffected):

```json
{
  "default": "code-review",
  "uploads_enabled": true,
  "foundations": [/* unchanged */],
  "session_sources": [
    {"id": "claude", "label": "Claude Code", "path": "~/.claude/projects", "available": true,
     "detail": null},
    {"id": "codex", "label": "Codex", "path": "~/.codex/sessions", "available": true,
     "detail": null},
    {"id": "hermes", "label": "Hermes", "path": "~/.hermes/state.db", "available": false,
     "detail": "state.db not found"}
  ]
}
```

`POST /api/skills/{foundation_id}/analyze-history` request gains an optional source:

```json
{"days": 30, "model": "claude:claude-sonnet-4-5", "session_source": "codex"}
```

`session_source` is `claude | codex | hermes | null`; an unknown value is a `422` from pydantic.
The response's counters gain session fields:

```json
{
  "analysis_summary": "…",
  "file_modifications": [/* unchanged */],
  "history": {
    "days": 30, "reviews": 4, "threads": 11, "interactions": 3,
    "session_source": "codex", "sessions": 12, "exchanges": 9
  },
  "warnings": ["No codex sessions in the last 30 days were readable."]
}
```

An unavailable or empty source is a successful analysis with a warning and zero session counters —
never an exception, because the review half of the evidence is still valid.

## Target File Map

New:

- `backend/app/services/agent_sessions_service.py` — source catalogue, readers, correction scoring,
  `SessionDigest`.
- `backend/tests/test_agent_sessions.py` — fixture roots for all three formats, window filtering,
  malformed-input tolerance, caps, and the API round trip with a stubbed model.
- `frontend/src/components/EvolveHistoryModal.tsx` — the start modal (foundation, model, source).
- `docs/plans/phase_48_plan.md` (this file).

Changed:

- `backend/app/core/config.py` — three source overrides plus `agent_session_*` caps.
- `backend/.env.example` — the same settings, commented, with their defaults.
- `backend/app/services/skill_analyzer_service.py` — accept and merge a `SessionDigest`; prompt
  section and task wording; adapted `META_CONTRACT`.
- `backend/app/schemas/skills.py` — `EvolutionSessionSource`, `EvolutionAnalyzeRequest.session_source`,
  `SkillsResponse.session_sources`, `SessionSourceRead`, extra `EvolutionHistory` counters.
- `backend/app/api/routes/skills.py` — populate `session_sources`; pass the source to `analyse`.
- `backend/rules/conventions.md` — service roster entry; `backend/rules/privacy.md` — local session
  transcripts are read only on request and leave the machine only in the chosen model's prompt.
- `frontend/src/types/index.ts`, `frontend/src/services/api.ts` — the new fields and the optional
  argument, in that order.
- `frontend/src/pages/SkillsPage.tsx` — header button, modal state, source-aware stage list; the
  old evolve card removed.
- `frontend/src/components/SkillEvolutionModal.tsx` — header line mentions the session source and
  counts when present.
- `README.md`, `CHANGELOG.md` — feature description and the Phase 48 entry.

Left alone: `skills_service`, apply/clone routes, analytics, the review flow, and every agent tool's
own files (read-only access only).

## Ordered Steps

1. Config: three directory overrides and the three caps; document them in `config.py` comments.
2. `agent_sessions_service.py`: `SessionDigest`, `available_sources()`, `summarise(source, days)`,
   one reader per tool, shared correction scorer/renderer. Fault tolerance per file and per line.
3. `skill_analyzer_service`: `analyse(..., session_source=None)`; `build_meta_prompt` gains an
   optional sessions block; `AnalysisResult` carries the session digest; no behaviour change when
   the source is `None`.
4. Schemas + routes: additive fields only; `analyse-history` passes `payload.session_source`.
5. Tests: three format fixtures with one in-window and one out-of-window session each, a malformed
   line, and an API test asserting the excerpt reached the prompt and the counters came back.
6. Frontend: types → api → `EvolveHistoryModal` → `SkillsPage` header button (card deleted) →
   workbench header counters.
7. Docs: README, CHANGELOG, rules roster and privacy note. Fix this plan if the build diverges.
8. Gates: `cd backend && pytest -q`; `cd frontend && npm run build`.

## Verification

- `pytest -q` green, including the new session tests.
- Service-level evidence with a real folder: `available_sources()` reports all three roots, and
  `summarise("claude", 30)` over the operator's real `~/.claude/projects` returns a non-zero
  session/exchange count with a bounded digest (no content printed, only counts).
- `GET /api/skills` returns three sources with `available` flags matching the filesystem.
- Browser: header button opens the modal; Start with no source behaves like before; Start with
  `codex` shows the session stage, and the workbench header reports the session counts.
- `npm run build` green; `alembic_version` unchanged at head.
