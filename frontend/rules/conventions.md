# Frontend rules

Applies to everything under `frontend/`. The root `AGENTS.md` still governs; these are the local
details that would be noise at the repo root.

- **New screens**: page in `src/pages/`, route in `src/App.tsx`, nav entry in
  `src/components/Navbar.tsx`. All three, or the screen is unreachable. `App.tsx` routes them behind
  `RequireAuth`; only `/login` and `/signup` are public.
- **Account state** comes from `useAuth()` (`@/context/AuthContext`); never persist a token or user
  object in `localStorage` — the session is an HttpOnly cookie and `me` is the source of truth.
- **API first, then UI**: add the interface to `src/types/index.ts` and the call to
  `src/services/api.ts` before wiring a component. Components receive data as props; only pages and
  the components that own a fetch call `api`.
- **Never** call `fetch` outside `src/services/api.ts`, and never hardcode `/api` paths elsewhere —
  `BASE_URL` lives in that module and the dev proxy is configured in `vite.config.ts`.
- **Primitives** (`Button`, `Card`, `Input`, `Badge`) stay in `src/components/ui/` and accept
  `className`; feature components stay in `src/components/`.
- **Styling** uses the Tailwind tokens only (no hex values, no CSS modules, no second UI library).
  Use `cn()` from `src/lib/utils.ts` for conditional classes.
- **TypeScript is strict** (`tsc -b` with `"strict": true`): no `any`, no unchecked optional access.
  `npm run build` is the gate; there is no test runner in this package.
- **Copy is product copy**: sentence case, no exclamation marks, and error text states what to do
  next ("Add a key in Settings") rather than what failed.
- **Drafts stay in memory** until the bulk `discuss` submit; typing never hits the network.
- **Workspace** (`/reviews/:id`): left = code context (`CodeSnippetBox`, line/origin rail), right =
  discussion (`CommentBox` → `RoundPanel`, `#N` chips, decisions); `ThreadFilterBar` filters both
  panes without renumbering `#N`. `SetupGate` sends `/` to `/setup` while the server reports
  `needs_setup: true` — never compute that client-side.
