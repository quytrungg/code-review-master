# Phase 37 — Theme toggle (light/dark) and nav order

## Summary (plain language)

The assistant is dark-only and the navbar leads with PR Inbox. After this phase a sun/moon
toggle sits immediately right of the Settings tab and flips the whole app between the existing
dark theme and a new light theme, remembered across reloads. The navbar order becomes Reviews →
PR Inbox → Skills → Analytics → Settings. What it deliberately is not: a per-page or
per-component theming system, a third theme, or a server-side setting — the preference lives in
`localStorage` on this browser only.

## 1. Objective & Scope

**In scope**

- Tokenize the palette: every Tailwind token color moves from hard-coded hex in
  `tailwind.config.js` to an RGB-channel CSS variable (`--canvas`, `--ink`, …) so opacity
  modifiers (`bg-canvas/80`, `ring-accent/40`) keep working under both themes.
- Light palette values for every token plus the card shadow; dark values are byte-identical to
  today's hex so dark mode does not change one pixel.
- `data-theme="light"` on `<html>` switches the palette; the default (attribute absent) is the
  current dark theme. Choice persists in `localStorage["theme"]` and is applied before first
  paint from `main.tsx` (no flash, no auth dependency — theme is not account state).
- Toggle button in `Navbar` immediately right of the Settings nav item: Sun icon when dark (the
  click makes it light), Moon when light; labelled "Switch to light/dark mode".
- Nav order: Reviews before PR Inbox.
- `.md-body strong` is currently `text-white`, which would vanish on a light card: it stays
  `text-white` in dark (default) and gains a light-only override to `text-ink`.

**Out of scope**

- Backend, API, schema — nothing changes there. No migration.
- Charts: no component uses inline hex (verified by grep), so all surfaces inherit the tokens.
- Per-account theme sync; system-preference detection (default stays dark, matching today).

## 2. High-Level Design

```mermaid
flowchart LR
    P[localStorage theme] -->|main.tsx, pre-paint| H["html[data-theme]"]
    T[Navbar toggle] -->|click| S[lib/theme.ts setTheme]
    S --> H
    S --> P
    H -->|":root"/"[data-theme=light]" block| V["--canvas/--ink/... channels"]
    V --> C["tailwind.config: rgb(var(--token) / <alpha-value>)"]
    C --> UI[All components unchanged]
```

One attribute on `<html>` is the whole state space; every component is untouched.

## 3. API Contracts & Schema

None. No endpoints, no schema change, **no Alembic revision**.

Light palette (chosen values; contrast-checked against white surfaces):

| Token | Dark (unchanged) | Light |
|---|---|---|
| canvas | 11 13 18 | 246 247 251 |
| surface | 18 21 29 | 255 255 255 |
| surfaceMuted | 23 27 37 | 238 241 248 |
| border | 35 40 56 | 219 224 236 |
| borderStrong | 47 54 80 | 190 199 219 |
| ink | 230 233 242 | 26 32 48 |
| inkMuted | 154 163 187 | 88 99 123 |
| accent | 124 139 255 | 91 107 250 |
| accentStrong | 91 107 250 | 74 90 234 |
| success | 61 220 151 | 13 158 110 |
| warning | 244 193 93 | 180 83 9 |
| danger | 255 107 129 | 209 47 77 |
| add | 18 53 31 | 216 243 226 |
| del | 58 21 32 | 252 228 232 |

`--shadow-card`: dark keeps today's value; light becomes `0 1px 0 rgba(255,255,255,0.6) inset,
0 10px 30px -22px rgba(26,32,48,0.25)`.

## 4. Target File Map

- **Changed** `frontend/tailwind.config.js` — colors become `rgb(var(--token) / <alpha-value>)`,
  `boxShadow.card` becomes `var(--shadow-card)`.
- **Changed** `frontend/src/index.css` — `:root` declares the dark channels + `data-theme=light`
  block declares the light ones; the light block restates `color-scheme`; light override for
  `.md-body strong`.
- **New** `frontend/src/lib/theme.ts` — `getTheme()`, `setTheme()` (sets `html[data-theme]` and
  persists), `toggleTheme()`; `initTheme()` called from `main.tsx` before render.
- **Changed** `frontend/src/main.tsx` — call `initTheme()`.
- **Changed** `frontend/src/components/Navbar.tsx` — theme toggle button right of Settings;
  link array reordered to Reviews, PR Inbox, Skills, Analytics, Settings.

## 5. Ordered Steps

1. Write this plan.
2. `tailwind.config.js` + `index.css` tokenization; `npm run build` — dark mode must be
   pixel-identical (same RGB triplets).
3. `lib/theme.ts` + `main.tsx` wiring.
4. Navbar: reorder + toggle.
5. `npm run build` gate.
6. Live check in a real browser: toggle flips every surface (navbar, cards, code panes, markdown
   strong text), reload keeps the choice, nav order is Reviews → PR Inbox. Screenshot both.
7. CHANGELOG entry + README if it states nav order (it does not — no change).

## 6. Verification

- `cd frontend && npm run build` green.
- Manual (browser): with the toggle in dark, a page screenshot matches today's look; after one
  click every pane is light, `.md-body strong` reads on white, the unread badge and active nav
  ring still read; reload → still light; toggle back → dark. No backend involvement.

## 7. Execution record

Executed 2026-11-11 (alongside other sessions' phases 32–36, left untouched).

- `npm run build` (`tsc -b` + vite) green before and after the changes.
- Live in a real browser against the scratch backend (:8011) and the throwaway account:
  nav order reads **Reviews | PR Inbox | Skills | Analytics | Settings**; the toggle sits
  immediately right of Settings (Sun in dark, Moon in light). Dark is byte-identical (same RGB
  channels, verified on the dashboard). One click → `html[data-theme=light]`,
  `background-color: rgb(246, 247, 251)`, and the review workspace (cards, badges, verdict
  buttons, AI opinion bar, message bubbles) renders cleanly; `.md-body strong` measures
  `rgb(26, 32, 48)` on a white card. Reload keeps light mode; toggling back removes the
  attribute. Backend process stopped afterwards.
