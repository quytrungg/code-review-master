# Web Review Rules

These rules apply to the HR web app only, and are read after the shared frontend rules. They cover module and route wiring, React state and effects in the browser, Hero Design and accessibility contracts specific to the installed components, internationalization, forms, API hooks, filters and tables, source organization, the web test and evidence mechanics, and the browser-side counterexamples. Authorization, data-fetching state, types, test-authoring quality, evidence layers, and the naming and feedback conventions live in the shared file and are not repeated here.

## Module, route, and authorization wiring

Must when introducing or changing a routed feature, scoped to the actual entry and owners.

- Trace the rendered route before changing a permission-gated page.
- For a new HR web app module, verify the current three-touch module wiring. Then inspect only the owners the path actually uses: `routeConfig`, `publicRouteConfig`, or a special app entry; module/index export; reducer/store; epic/effect; provider; and permission mapping.
- Prefer the current `authorizationV2` shape for new authenticated routes. Do not require an untouched legacy route to migrate merely because it uses the older contract.
- Use the existing owner and selector for a resource, permissions included. Do not add a second fetch, a second refetch path, or a widened API version scope without proving the current path requires it; two triggers that both call the same fetch issue one request each and race to write the same slot.
- Check a readiness handler for an error value that can be the empty string. `dataReadyHandler(loading, data, error)` reports ready only when `error` is non-empty, so a bare `{ status: 500 }` parses to `error === ''`, stays not-ready, and spins forever instead of reaching the retryable `<Result>`.
- When a gate is added to a module that already owns a permissions request, require the key in that module's `apiCalls/getPermissions` and read it through the module selector. A `useCheckFeatureFlag` read inside a component issues a request per mounting instance and leaves the module with two sources of truth that can disagree.

Report missing wiring only when the current module contract requires it and the changed feature is unreachable, unguarded, or incorrectly registered.

## React state and effects

- Reset page to `1` when a material filter changes and the endpoint's pagination contract would otherwise request an invalid/stale page.
- When reviewing a widened mount condition, read the first guard inside the mounted component before accepting the widening. A second key checked there, commonly a legacy uplift flag published only for a narrower cohort, returns `null` and the widened outer gate renders nothing at all; the outer gate and that inner guard have to resolve through the same selector.
- Prefer component or store state for a value render reads, and reserve `useRef` for a value no render depends on: a ref update neither schedules a render nor appears in devtools, so state written through a ref shows a stale UI and a poll that reads it misses the update that should have restarted it.
- A ref, default parameter, or lazily-initialised state seeded from a prop captures the first render's value. When the prop can change identity, seed from state and reset on the new identity, or derive the value at use instead of storing it once.
- Do not declare components inside components. Inline one-off JSX or extract a named component; a nested declaration remounts on every parent render and defeats memoization.
- Compose at the call site rather than threading data through a helper. Passing a value into a helper that only forwards it creates an illusion that the helper owns it; spread it at the caller instead.
- Keep branch shape aligned with the actual states: `true`, `false`, and `null` are not interchangeable. A gate that checks only `=== true`/`=== false` silently misses the absent/legacy `null` state.
- Keep props types scoped to one component; move shared concepts to `types.ts` once multiple files consume them.
- For large UI work, separate composition/routing, state/effects, pure transforms, visual sections, contracts, and tests only where each concern has independent ownership.
- Gate the hook call, not the JSX it feeds. Hooks run unconditionally before any `&&` in the return, so `{ff && <Section/>}` removes output while the flag read, the permission selector, and the data hook above it still execute their effects, fetches, and tracked events on every render.
- Do not mount a form or wizard before the request that shapes it has resolved. A mounted form captures `initialValues`, its default step, and its first option list once, so a draft arriving in a later commit either leaves the stale default or forces a re-initialisation that discards what the user typed.
- Treat an "already ran" `useRef` latch in an effect as the symptom of a wrong dependency array: the latch exists because the effect also depends on `fields`, a destructured callback, or an options array whose identity changes every render. The repeats are swallowed, but the body still runs and the latch is invisible to lint.
- Hoist module constants out of the component, and memoise only a collection that crosses a dependency array, a memo boundary, or a `setState`. A `.filter`/`.map`/object literal in the body is a new reference every render, and feeding one to `setState` inside an effect re-runs the effect on the state it just wrote.
- Use the hook's `onComplete` instead of a watcher effect on `[fetching, data]`, and derive the next polling step from the returned result rather than forcing `SEQUEL_FETCH` inside the fetcher.
- Do not add, reorder, or extend a dependency array without naming the re-run it must cause. One-shot reference data and its scalar `isLoading` readiness flag have no identity churn to defend against, so the dep only creates a second trigger; a function identity that can change does belong there.
- Call the hook where its data is consumed. A hook lifted into a parent only to hand `fetchData`/`refetch` down keeps the subscription, the loading flag, and the cache entry there, so every fetch-state change re-renders the parent and its siblings; a one-line `const handleRetry = () => fetchData()` adds a fresh identity per render and no behaviour.

## Selectors and derived state

- Build a memoized selector with `createSelector` when its result is an array, an object, or a value a dependency array consumes. A plain function returns a new reference on every call, so `useSelector` compares unequal each render and every memoized consumer re-renders with it; `createSelector` returns the previous result when the inputs are unchanged.
- Search the module for an existing selector over the same slice before adding one, and name the difference when you keep the new one. Two selectors over the same inputs are two sources of truth that drift apart on the next change; a deliberate temporary duplicate carries the canonical selector's name and a removal condition in a comment.
- Keep a selector's output reference stable when it reaches an effect, a dependency array, or a child's props. A selector that returns `Object.values(map)` or `.filter(...)` builds a fresh array per store update, so the effect or poll it feeds restarts on state that did not change.
- Never place a ref in a dependency array. Its identity never changes, so the entry never fires and the effect closes over the first value it saw; read `ref.current` inside the effect body and depend on the value the ref mirrors.

## Hero Design and accessibility

- Use Hero Design components first. Do not hand-roll an equivalent control without a demonstrated component gap.
- Follow current Hero API contracts. Known patterns include:
  - `Filters.Trigger` hidden state renders `undefined`;
  - mandatory `Filters.Filter` supplies both `onChange(value)` and `commit(value)`;
  - filter labels use `leftAddon={() => <Filters.Label />}`;
  - `FilterValue` is a type import;
  - `Table` uses `noData` and a boolean `loading`;
  - `Tag` intents must be supported by the installed Hero version.
- Treat an exact prop recipe as version-scoped. Confirm the installed component contract before raising it.
- Clear a modal's transient state in its close path, not at the next open, and hand the mutation the complete entity the modal was given rather than a hand-picked slice such as `{ id: rowData.id }`.
- Render `Modal` last in the returned tree, and drive a multi-step flow from one explicit state value instead of opening a second modal from inside the first. Hero modal surfaces share a stacking context, so at equal stacking the later element in the tree paints on top and receives the click.
- Check the precondition the client already holds before firing a mutation, and derive a control's pending and disabled state from the in-flight request rather than from a second condition.
- Route spacing through the layout primitive (`Box margin`/`padding`) and colour and typography through the Hero theme scale. An inline `style` object restates a value the theme scale already owns and bypasses skin and theme overrides; suppress for a known-temporary adjustment the author expects to be replaced.
- Adjudicate a pixel change against the demo capture attached to the PR, not against a linked ticket, and keep contrast, density, and overflow findings non-blocking unless the defect hides information.
- Resolve a suspected Hero prop mismatch against the installed declaration or the docs it ships with; a hedged recollection or a recipe from another app is not evidence. `Spinner` takes `text` rather than `loading`, and `font size` accepts a raw number.
- A merely different DOM structure is not itself a finding.

## Internationalization

- Reference the global SWC `t` macro directly; never import `t`.
- Keep plural grammar inside ICU syntax rather than concatenating counts or branching English in code.
- Call `Intl.formatMessage` inside a function body or `useMemo`, not as an eager module-scope value.
- Build module-scope translated configuration through a factory. Route-config `title` and applicable breadcrumb text use the current callable form rather than root-scope translation.
- Preserve an existing key when meaning and context remain the same. Create a scoped key when one key spans unrelated meanings.
- Add every new message id to the `en-AU` base file and drop an override whose text equals the base value. A regional file is an override layer, not a copy of the base: the installed resolver falls back per message to `en-AU` then to the id, so a new id needs no entry in `en-GB` or `en-CA` and its absence there is not a finding. The defect is the inverse — an id that exists only in a regional file, which renders the raw id in every locale the base serves.
- Require the `t` macro for every id the diff introduces, and use `t({ id, message })` rather than `Intl.formatMessage({ id })` when touching an existing id: `t` is a compile-time SWC macro and its `message` becomes the `defaultMessage` the resolver consults before falling back to the id.
- Reject a `*` baked into a message value. The field's own `required` prop owns the marker, and an asterisk inside the string enters the accessible name, is announced as "asterisk", and cannot be restyled by the design system.
- Check that a new id names the slot it fills (`.title`, `.description`, `.error`) and that its value belongs to its namespace. An id generated from the English sentence, or a feature-named id holding body copy, is the scope contract going wrong.
- Do not ask for a shared key until a third consumer exists or the meanings have diverged. Lifting a string out of its feature namespace makes every future copy change a cross-feature negotiation.
- When a diff edits locale copy, check it against the requirement and that locale's established terminology, sweep the sibling keys that share the term, and ask for the PO answer instead of proposing wording.
- Open the call site of every added or edited message and confirm each placeholder exists in the values object. A mismatch is not degraded: `intl-messageformat` throws that the context variable was not provided, so the branch dies.

## Forms

- Use HeroForm/form-v2 for new or explicitly migrated forms.
- In a migration, preserve current behavior first: validation timing, dirty state, submission, reset, dynamic fields, error display, and request payload.
- Do not demand cleanup or framework-wide refactoring in the same change unless the task includes it.
- Legacy form libraries may remain on untouched paths; migration parity is contextual, not a universal defect.
- When a field is gated as required in code, confirm the spec, acceptance criteria, and manual verification steps agree. A code/spec contradiction makes the manual checklist fail as written; flag it and ask which contract wins rather than assuming the code is right.
- Hoist a field's `validate` and `options` arrays out of the render body: module constants when unconditional, `useMemo` when they depend on props. `Field` re-registers whatever array it is handed on each render, so an inline array is a new validation contract every time.
- When a section stops rendering or becomes read-only, clear the values it owned and keep their validators. Unmounting a `Field` does not remove its value from redux-form state, and the same flag that hides it usually strips its `validate` array, so a hidden field is submitted without validation.
- Decide whether a field changed against `getFormInitialValues`. A `!!value` test collapses `false` into absent, so clearing a checkbox emits no request, and a `touched`-gated check never fires for a value the user did not edit.
- Filter a select's options on the row's discriminating field, not on the container's type: `Array.isArray(c.timesheet_accrual_rules)` is true for every category row, so a TOIL-only predicate admits everything. Clear or refetch the stored value whenever the parent key or the option set changes.
- Write each logical value to one field name and let the serialiser decide the payload shape. Never let `isFormDirty` select the field name or the value source: a generator and its paired `onChange` that switch on opposite polarity make the payload key depend on edit order.
- Derive a form's default value from the fetch or store state that owns it, on every code path that renders the field. `useState(defaultFromFetch)` initialises before the fetch resolves and never re-runs, and a `new Date()` inside a permission-gated selector is stale for every other member.
- When a field is gated as required, check that its `validate` array still proves the type submit expects. The array reports the first error, so `[required, numberRequired, positiveInteger]` makes the user's message depend on position while the later validators stay unreachable.
- Leave a value the API did not send absent in form state. `String(initialValue || 0)` in a shared inline-editing hook writes `0` for `undefined`, `null`, and `''` alike and hands it back on blur, so every call site commits a value the user never entered.
- Read form values through `formValueSelector`/`getFormValues`/`getFormInitialValues`, and keep non-value flags such as `disabled` as form fields rather than mirroring them into a React context beside redux-form.

## API hooks, filters, and tables

- For established `useApi` usage, dependencies must contain the identity/params that should refetch. Use the repository's current notification convention for read-only fetches.
- Keep endpoint-specific filters and pagination with the table section they control. Do not assume sibling endpoints accept identical parameter names or omission semantics.
- Debounce network-driving filter state where current peers and UX require it; tests may replace the debounce with a deterministic passthrough.
- During a staged Hero filter migration, preserve the current values, reset behavior, warnings, search, pagination, and test affordances that belong to that slice. Raise only a demonstrated parity regression; do not impose one universal migration sequence or require future phases in the current PR.
- Convert pagination strings to numbers when the API contract is numeric.
- Preserve full multi-value arrays; map/filter the full value rather than silently using the first item.
- Render null/undefined fallback at column creation, commonly `value ?? '—'`, while preserving the transport value.
- Handle an empty array explicitly before mapping where empty has a distinct display contract.
- Mock fetch-options responses using the real envelope used by the current hook; do not generalize a historical `{ data: { items: [...] } }` shape to unrelated APIs.
- Put an identity that shapes the request (organisation, member, employee, scan id) in `useApi`'s `deps` array or pass it through `fetchData(params)`. Interpolating it into the endpoint string builds a new URL every render while the hook keeps the fetcher captured at mount, so the request does not follow the identity.
- Debounce the value, and keep the debounced function referentially stable. `debounce(delay, fn)` built in the component body allocates a new timer every render and orphans the pending one, so the final keystroke is dropped and the list shows results for an earlier query; use `useDebounce` with an effect on the debounced value.
- In an items-per-page handler forward both `Number(value)` and the page index held in state, because the setter updates component state and does not refetch on its own. Declare pagination fields required in the hook's params generic when the hook is never called without them.
- Build request params with `generateGetURL(base, paramsObject)`, which encodes values and drops nil entries. A hand-interpolated `?key=${encodeURIComponent(value)}` double-encodes values containing `&`, `/`, or a space and serialises `undefined` as the literal string.
- Call a `...SelectorCreator({ host, version })` once and `useSelector` the resulting scope path, then build the endpoint in `extractEndpoint` from `params`. Do not name a creator `...Selector`, and do not branch on `typeof endpoint === 'function'`, which lets a creator land in the function slot without an error.
- Confirm the endpoint's complete-set semantics before adding a pager or a `page` param: a paginated fetch with client-side search searches only the loaded page, and a `page` param on an endpoint that returns everything makes the pager lie about the total.
- Compare a hardcoded `staleTime` or cache TTL against the screen's stated refresh cadence, and treat a 304 as browser revalidation rather than an app cache hit. A five-minute `staleTime` on a dashboard specified to re-read every 20 seconds serves the whole window from cache.

Raise a finding only for a concrete request, rendering, cache, or state consequence — not for deviation from an incidental peer shape.

## Components and source organization

- Every new frontend-core file or folder requires CODEOWNERS coverage unless a newer path-specific instruction explicitly supersedes the root rule.
- Check every fetch-in-an-effect hook against its mount count: with more than one simultaneous mount point the fetch belongs at the module or route root, with one consumer it belongs in the component that renders the data. `autoCleanUp: false` keeps the response but does not dedupe concurrent callers.
- Import from the file that declares the symbol, not from a sibling's `index` barrel: the barrel re-exports consumers, so a value import closes a cycle that initialises in a different order than the module graph reports.
- Trace any import that leaves its module. It must resolve through `modules/shared/<domain>` or a `packages/eh-utils` entry, and module-specific logic must not be added to those shared owners. A module `index.ts` re-exporting selectors and constants becomes a cross-module API, and a shared hook importing a component's `formatNumber` makes the hook depend on the component.
- Split by export status, not by file size. In a `Component/index.tsx` the single export is the owner, and every additional `export` becomes an independent import target whose props are now a public contract; a second component that only the owner renders stays unexported in the same file.
- When a PR clones a screen, find the shared visual section. Screens that differ only in data (icon, copy, options) stay one parameterised component; screens that differ in flow (create vs edit, employee vs open shift) share the presentational part, with each flow in a thin wrapper owning its submit and initial values.
- Report an optional prop or flag whose only non-default value comes from a test or from a caller that does not exist yet. The test then proves a branch production never takes, and the extra prop widens the contract before its second consumer exists.
- Constrain a private component's visual prop to the variants it supports, or collapse it to a boolean when only two states exist (`size: 'small' | 'large'`, not a `size` translated at every call site). Suppress for a genuinely continuous scale such as a chart or resizable panel.

## Web tests

- Give each scenario its own `it`. A spec that arranges two cases in one block stops at the first failing assertion, reports one name for two behaviours, and hides the second failure until the first is fixed.
- Use React Testing Library assertions on observable behavior.
- For API behavior, assert exact URL/method/params or payload, then assert the DOM/state after the awaited request boundary.
- Before inserting a test block, confirm the containing `describe` scope and the setup the new case inherits.
- Prefer `it.each` table form for any case that differs only in input and expected result, including locales that share the same behavior/flag; a table reads as the contract while a repeated block hides the one row that differs.
- Do not add or update snapshot tests in `frontend-core`; use explicit React Testing Library assertions. Mention an existing untouched snapshot only when the reviewed change makes it relevant.
- Test selectors should follow the component's current public/test contract; `Filters.Trigger` commonly uses `data-test-id="item-{filterKey}"`.
- Anchor an endpoint assertion at the start of the URL, not only with a trailing `$`. `getMainAppHost()` reads an environment variable, so a suffix-anchored regex accepts `undefined/api/v4/...` and passes on a base whose host is missing; assert `^${getMainAppHost()}/...` so an unset host fails the case. When a case asserts that a session value never appears in the path, confirm the fixture populates the slice the selector reads: `currentMembershipIdSelector` reads `currentMemberSelector`, so a hand-added `session.currentMembershipId` never reaches it and the negative assertion cannot fail.
- Write a request assertion as `await expect(fetchMock).toBeFetched(url, opts)`. A bare `expect(fetchMock).toBeFetched(url)` constructs the promise and discards it, so the test passes whether or not the request was made; `return expect(...)` is equivalent and a 304-style already-resolved mock is the only exception.
- Prefer an async matcher that asserts the awaited request boundary and the exact payload in one assertion (for example `await expect(fetchMock).toBeFetched(url, { body: {...} })`) over a `waitFor` plus a separate `JSON.parse`/`toMatchObject` on the captured body. A fetch matcher proves the request was made with the given body; it does not prove the response-driven re-render, so still assert the visible DOM/state after the awaited boundary.
- Await the request boundary once, then use synchronous `getBy*` for every DOM consequence. `findByText` resolves on whichever commit renders the text, which can be the same commit that starts the fetch, so a chain of them is not a chain of boundaries: the first asserts against pre-response state and the second waits again on an already-settled tree. Use `findBy*` only when the appearance itself is the contract and no request precedes it.
- Pair each query with the matcher that adds information. `getBy*` already throws when the node is absent, so chain `.toBeVisible()`; use `queryBy*` with `.not.toBeOnTheScreen()`/`.not.toBeInTheDocument()` for absence and `getAllBy*().toHaveLength(n)` for counts. `toBeDefined`, `toBeTruthy`, and `toBeInTheDocument` pass for a node that is mounted but hidden.
- Assert the outcome from `store.getActions()` or the fetch mock, and add the negative assertion that proves the guard did not also fire. `expect(dispatch).toHaveBeenCalledWith(action)` inside an epic proves only that the code's own call reached its own spy, and nothing about the log.
- In a parent or screen spec, render the real child and stub only the transport. A `jest.mock('./ChildForm')` stand-in re-declares the child's props and renders filler, so the parent→child contract never executes and the test cannot fail when the real child's props or guards change.

## Web validation and delivery

Use the current repository and package instructions, command names, and project names. Root defaults are Node `22.22.0+`, Yarn Berry `4.10.3`, and scoped Prettier; package-specific Jest/test-ci/lint-ci wrappers are what CI runs.

- The review gate's lint config (currently `eslint-code-review.config.js`, with root-relative paths) is run by CI, not here. When its result appears in the evidence, read it rather than reproducing it.
- Format touched files only when write authorization covers implementation cleanup; otherwise inspect and report gate status without formatting or mutating files.
- Add a changeset for an external library when current `project.json` metadata requires it.
- Depend on a sibling package in a private monorepo library's `package.json` with `*`, and reserve caret ranges for packages that are actually published: a caret on a private sibling resolves against the registry instead of the monorepo copy.
- Report warnings, skipped gates, and unavailable runtime evidence explicitly.

Do not call a change shipped because source, CI, merge, or deployment alone succeeded.

## Web evidence

- Focused React Testing Library tests prove component behavior under their mocks.
- API mock assertions prove client request construction, not server acceptance.
- Browser-driven E2E evidence proves only the exercised route, account, flag, permission, and environment.
- A source route match does not prove redirects, authorization, or runtime data.

### The app's own checks are CI's

Jest and the `tsgo --noEmit` type-check belong to the pipeline. This review does not run them, does not create a worktree for them, and does not switch a shared checkout's branch for them: a local run is a simulation against one revision, and the pull request's own check run on the head is the evidence.

What the evidence class still decides: the app's type-check is **not** green at base, so a standing set of errors in modules the change never touches is normal, and the usable assertion is that the error **file surface** is unchanged between base and head and that no touched file appears — never that the command exits 0. A green JavaScript suite never proves a native or background integration.

## Web gotchas

### UI and forms

- Filter pagination reset and debounce are endpoint/UX-specific. Require a concrete stale-page or request-volume consequence.
