# Phase 49 — Drop the agent session folder from the evolve start dialog

## Objective & Scope

**In.**

- The **Evolve from review history** dialog on the Skills page keeps only the two choices that make
  sense once the app runs on a server: the **skill foundation** and the **model**. The
  **Agent session folder** select (Claude Code / Codex / Hermes local stores) and its hint copy are
  removed.
- The analysis is therefore always driven by one evidence source: past reviews, their findings and
  the user's corrections in the comment threads (`aggregate_history`), which is what
  `analyze-history` already does when `session_source` is absent.
- The frontend stops sending `session_source`; the progress-stage list drops its session branch, so
  the stage the runner shows is the review-history one.
- `README.md` (Skills section) and `CHANGELOG.md` describe the dialog as review-history only.

**Out.**

- No backend, schema, migration or prompt change: `backend/app/services/agent_sessions_service.py`,
  the `session_sources` field of `GET /api/skills`, the `session_source` body field and its tests all
  stay exactly as they are. The API keeps working for a local operator who wants it; only the UI
  stops offering it. Purging that backend support is a separate decision (see "Open question").
- No change to the foundation/model pickers, the workbench modal, apply/clone, or the
  `history.session_source` display in past analyses (it renders only when an old analysis has one).
- No change to how review history is aggregated, scored or cited.

## High-Level Design

```mermaid
flowchart LR
  B[Skills header button] --> M[Evolve dialog<br/>foundation · model]
  M -->|POST analyze-history {days, model}| R[skills route]
  R --> S[skill_analyzer_service.analyse<br/>session_source defaulted to None]
  S --> H[aggregate_history<br/>reviews + comment-thread pushbacks]
  H --> P[build_meta_prompt]
  P --> L[one evolve LLM call]
  L --> W[workbench modal]
  X[session folder picker] -.->|removed| M
```

The dialog payload loses one optional key; the route's default (`session_source: null`) is the exact
behaviour the dialog produced when its select was left on "None".

## API Contracts & Schema

**No API contract change on the server.** The dialog simply stops sending the optional field:

```json
POST /api/skills/{foundation_id}/analyze-history
{ "days": 30, "model": "claude-sonnet-4-5" }
```

The endpoint still accepts `{"session_source": "claude"}` from other clients, and still answers
`history.session_source: null`, `sessions: 0`, `exchanges: 0` for this dialog's requests. The
`GET /api/skills` response keeps its `session_sources` array (unread by the UI after this phase).

**No Alembic revision.** No table or column changes.

## Target File Map

Changed:

- `frontend/src/components/EvolveHistoryModal.tsx` — drop the `sessionSources` prop, the
  `sessionSource` state, the select block and its hint, the `FolderSearch` icon, and the
  `SessionSource` / `EvolutionSessionSource` imports; `onStart` narrows to
  `{ foundation, model }`.
- `frontend/src/pages/SkillsPage.tsx` — `evolutionStages()` loses its `source` parameter and the
  session stage; `evolve()` loses its `sessionSource` parameter and the `source` lookup; the modal
  call site stops passing `sessionSources`; unused type imports go.
- `frontend/src/services/api.ts` — `analyzeSkillHistory(foundationId, days, model)` sends
  `{ days, model }`.
- `README.md` — Skills section sentence about the dialog and the one local session folder.
- `CHANGELOG.md` — a Phase 49 entry recording the removal under **Removed**/**Changed**.

Left alone:

- `frontend/src/types/index.ts` — `SkillsResponse.session_sources`, `SessionSource` and
  `SkillEvolutionHistory.session_source` mirror the pydantic schemas and stay.
- `frontend/src/components/SkillEvolutionModal.tsx` — its `session_source` line renders only for a
  history that carries one, which this dialog can no longer produce.
- Everything under `backend/`.

## Ordered Steps

1. `services/api.ts`: shrink `analyzeSkillHistory` and its type import; `npx tsc -b` still resolves
   call sites (they are fixed in step 3).
2. `EvolveHistoryModal.tsx`: remove the picker, state, icon and prop; keep the existing
   foundation/model/notice layout and the "This sends the foundation's rules…" info line.
3. `SkillsPage.tsx`: simplify `evolutionStages()` and `evolve()`, update the modal call site.
4. `README.md` + `CHANGELOG.md`: describe the review-history-only dialog.
5. Gates: `cd frontend && npm run build`; `cd backend && pytest -q` (unchanged, run as the
   definition-of-done check).

## Verification

- `npm run build` (`tsc -b` + vite) is green — that is the TypeScript gate for the removed prop and
  narrowed callback type.
- `git grep -n "sessionSource\|folder picker"` over `frontend/src` returns only the untouched
  `types/index.ts` schema mirrors and `SkillHistory` display, with no dangling prop or argument.
- `cd backend && pytest -q` is green, proving the retained backend support still behaves (the
  dialog's no-`session_source` request is the case `test_agent_sessions.py` already asserts:
  `history.session_source is None`).
- Manual read-back of the dialog source confirms the rendered fields are foundation and model only,
  with no `sessionSources` reference anywhere in `frontend/src` outside `types/index.ts`.
- A live browser pass needs a signed-in session on the local app; if the operator provides one, open
  Skills → Evolve and confirm the dialog shows two fields and the request body carries no
  `session_source`. Recorded as an open check, not claimed as done.

## Open question

Should the retained backend support (session discovery, `session_sources` in `GET /api/skills`, the
`session_source` body field, `agent_sessions_service` and `tests/test_agent_sessions.py`) be deleted
as well? This plan deliberately leaves it: it is tested, reachable by API, and harmless on a server
(the sources simply report unavailable), while deleting it is a much larger change that reverts
most of phase 48. Answer before that removal is attempted.

## Verification result

- `npm run build` (`tsc -b && vite build`) green — 1895 modules, `dist/assets/index-BPCgmI0T.js`.
  `npm run typecheck` also clean.
- Built bundle: `"Agent session folder"` → 0 matches; `"Evolve from review history"` → present;
  `"session_source"` → 2 matches, both the `SkillEvolutionModal` history line that must stay.
- `grep -rn "sessionSources\|session_source" frontend/src` → only `types/index.ts` (schema mirrors)
  and `SkillEvolutionModal.tsx` (past-analysis display). No dangling prop, argument or import.
- `cd backend && pytest -q` → 430 passed, including `tests/test_agent_sessions.py`, whose
  no-`session_source` case is exactly what this dialog now sends (`history.session_source is null`).
- Live browser pass not performed: the local app is behind account auth (`users` rows exist in
  `code_review`) and this session has no credentials for it. The dialog is props-only and its
  rendered fields are foundation + model; the operator can confirm in one click on Skills → Evolve.

