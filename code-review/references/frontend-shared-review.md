# Shared Frontend Review Rules

These rules apply to both surfaces — the `frontend-core` HR web app and the `eh-mobile-pro` React Native app — and are read before either surface file. They cover what is the same on both: authorization, permissions, and privacy; data fetching and loading/error/empty-state semantics; state ownership; identity and tenancy; transport contracts; types and nullability; accessibility semantics; test-authoring quality; evidence, CI, and delivery claims; and the conventions for naming, readability, and written feedback. Each surface file adds only what its own platform adds.

## Essential checks

- **Correctness and ownership:** trace input, identity, state, async/lifecycle owner, transformation, persistence, and output. Check null, empty, stale, failure, retry, cleanup, and migration states that the supported path can reach.
- **Authorization and privacy:** identify actor, tenant/member, permission, feature flag, server enforcement, and redaction owner. UI visibility and client guards are not substitutes for server authorization.
- **API and state:** verify the real endpoint, request/response shape, nullability, pagination, cache key, refetch identity, error semantics, and downstream consumers before proposing an adapter or shared abstraction. For a claimed replacement or migration, compare the established and proposed contracts before calling them compatible. Name the serializer or presenter that serves the exact route before declaring a client-visible field missing or wrong: sibling serializers in one domain expose different field sets, and a value computed in the serializer does not exist on the model. When a client gate looks inert, resolve the value at its source — serializer gate, feature flag, permission — instead of filing it as a client defect.
- **Rendering:** prefer the current design-system and localization contracts, preserve accessibility and behavior during migrations, and distinguish one-off inline markup from independently owned domain logic.
- **Guards and seeded inputs:** a guard is only as live as the object it reads. When a screen seeds its own state — an edit form hydrated from a fetched record, a detail screen from a route param — compare the seeded shape against the entity the guard expects. A flag present on the fetched collection but absent from the seed makes the guard permanently false on that path while staying true on the create path, which reads as intermittent rather than broken. Then trace the rendered disabled state to the primitive that owns the press: a component that honours `disabled` blocks the callback, one that only styles it does not, and the press handler may or may not re-check the guard. Check the handler and the disabled prop separately before calling either the guard or the control broken.
- **Loading gates and mount latching:** a gate that returns a different element while data loads unmounts the subtree it replaces. When the condition reads data that arrives after the first render (a flag, a permissions payload, a fetched slice), the subtree mounts first by definition, so the gate cannot prevent that first mount, and a later flip swaps a live form for a spinner and discards typed input. Latch the decision once the data is ready and keep it latched. Then check what resets that data: a sibling screen's unmount cleanup that resets the same slice flips the gate mid-run, which a first-render-only reading never shows.
- **Lifecycle and platform:** trace mounted lifecycle, background ownership, persistence, and replay registration. Navigation stack identity, platform/native configuration, and device runtime are separate proof layers from source.
- **Tests:** assert the observable contract with the smallest meaningful test. Require broader integration, E2E, platform, or runtime evidence only when the changed boundary cannot otherwise be proven or a current repository gate names it.
- **Delivery:** distinguish source, static checks, tests, CI, merge, deployment, and runtime. Apply current CODEOWNERS, changeset, module, toolchain, platform, and handoff gates as repository rules rather than stylistic preferences.
- **Conventions:** enforce only contextual, evidenced conventions. Never invent a fixed tone formula, mandatory refactor, memoization rule, comment style, deep-link rule, network policy, or migration sequence.

## Authorization, permissions, and privacy

Must. Typical severity: high; critical only when the table's Critical condition holds — raw protected data exposed, or a cross-tenant operation confirmed. Medium for presentation-only mismatch.

- Treat server policy/action checks as authorization. A client flag, hidden menu, disabled button, or route guard can improve presentation but cannot establish access control.
- Consume server-owned redaction/projection markers for sensitive values, and prefer server-generated identifiers. Do not infer permission from whether raw data happened to be returned, from client flags, or from raw field presence.
- Model permission/loading/unknown states fail-closed when a protected request or display would otherwise execute. Preserve explicitly documented legacy compatibility paths.
- Validate organization, member, tenant, and actor identity at the layer that owns the action.
- Treat feature flags as rollout/presentation controls. Server policy remains the authorization boundary.
- Gate permissions with `=== true`, never `!== false` or `if (!permissionBlocked)`. Permission values reach the component as `boolean | undefined` — permission types carry optional keys — so `!== false` treats the pre-load state, and any key the endpoint version does not return, as granted. This is the authorization case, where an absent value must block; a three-state display branch still needs its own `null` branch. Report only when the selector's declared return type is optional; a non-optional `boolean` from an endpoint that always returns the key is fine.
- Report a request field computed from a client feature flag so the backend branches on it (`async_create: !!canUseAsyncCreation`). The server then takes a different path per client build and rollout bucket instead of per its own record of the organisation's capability.
- When a client rule keys on a value the API supplies — a prevention flag, an eligibility boolean, an available balance — read the serializer that produces it and evaluate it for the exact member. Feature flags, organisation type, and the current member's permissions can force that value false for the accounts used to test, leaving a correct-looking rule permanently inert. A test fixture that sets the field by hand proves the branch, not the contract.
- Keep shared fixtures false/absent for optional capabilities; enable capability only in the test that exercises the authorized path.
- Verify protected requests do not start before authoritative readiness, and start optional requests only after required authentication and identity context are ready.
- Verify redacted values come from the server marker/type contract and raw protected data is not rendered.

Suppress when current source proves the endpoint is public/non-sensitive, the server guarantees an immutable scoped credential context, or a named migration contract intentionally preserves older behavior.

## Data fetching, loading, empty, and error states

- Choose the loading, empty, and error branch from the fetch hook's own `loading`/`isFetching`/`error`, with one such flag per request. A gate written `data ? <List/> : <Spinner/>`, or `if (!dataReady) return <Spinner/>`, is correct only for the first request of the mount: the data-ready flag is set once and never cleared, while `isFetching` tracks every request.
- Drive the in-flight window from the hook's `loading`, not from a boolean set in `onComplete`. That flag never returns to false when the next request starts, so a filter, page, or sort change renders the empty state against the previous payload for the length of a round trip.
- Branch on emptiness and on the not-found terminal state explicitly. `[]` and `{}` are truthy, so `buttonGroup ? <Group/> : <Button/>` never reaches the fallback, and `loading` alone leaves no branch for `!loading && !record`, which keeps a 404 or a denied id spinning forever.
- Preserve explicit readiness and error states; do not translate every terminal response into success or every unknown value into loading.
- Do not treat a constant interval or elapsed time as evidence that the backend finished. Poll the known ids until their status is terminal or follow the returned polling job; `setInterval` plus a duration `setTimeout` refetches the whole list on a clock with no in-flight guard.
- Give a resource one refetch owner. A callback prop and an effect that both call the same fetch issue a request each on every change and race to write the same store slot, so which response wins depends on timing rather than on the last user action.
- A successful status or terminal job state does not prove a mutation, ledger write, replay, downstream effect, or user-visible completion.
- Stop a poll on 401, 403, or 404 instead of retrying. An unauthorized or missing resource does not become available on the next tick, so the retry loop only extends the failure and keeps the in-flight flag set for the whole deadline.
- Let a hook that more than one screen consumes catch its own request failure and return a fallback state. A rejection that escapes a shared hook surfaces in every caller's render, so one screen without an error boundary crashes on a failure the hook already knows how to describe.
- Client cache invalidation is not automatically necessary if the owning query key, immutable context, or server push contract already handles freshness.
- Exercise explicit failure and recovery behavior when the feature owns it; do not assert one global toast/retry pattern.

## State ownership and duplication

- Use component state for component-only visibility, one-shot guards, transient selection, and toast timing. Use established Redux/query/provider state for cross-component concerns.
- Derive values instead of duplicating server/store state unless an explicit editable draft owns divergence.
- Compute a value that props or store state already determine with `useMemo`; do not copy it into `useState` and write it back through a sync effect. `useState(status)` plus `useEffect(() => setCopy(status), [status])` keeps a second source of truth with its own render pass, and the `useState('')` variant makes every guard false while the value is unresolved. Keep the copy only when the prop is a starting value the user is meant to diverge from, such as an editable draft.
- Include every value that changes an effect's meaning and every identity-changing input in fetch/cache/effect ownership, and clear stale results when that identity changes. Pay special attention to organization/member identity, permission readiness, route params, pagination, and filters.
- When a component starts writing a **shared** store slot for a subject other than the session's — another member, another tenant — enumerate every consumer of that slot's selector and split them into dispatchers and readers. A cache keyed by action type carries no subject in its key, so a reader that never fetches renders whichever subject wrote last: a permission block written for a viewed employee then drives a widget or report modal that assumes the session member. Two mechanisms make this survive review: the in-flight flag masks the swap only while a request is running, and a readiness helper that treats a non-empty error as ready (`dataReadyHandler(isFetching, data, error)`) reports ready for a member whose fetch failed while the previous member's payload is still in the slot. Give the non-session read its own slot, key the action by member, or clear the slot on unmount.
- Depend on the derived scalar, not on the collection: `isEmpty(permissions)` compares by value, while a selector or inline `.filter` hands back a fresh array on each store update and each render.
- Every timer, subscription, listener, background job, and dynamic fixture needs a lifecycle-aligned cleanup owner.
- Do not assume navigation always unmounts a screen or that a mobile process remains alive.
- A guard at the mount boundary beats a guard in the render output: a condition checked only inside the render path still mounts the component and fires its effects.

Suppress when immutable context, a complete tested cache key, or an owning framework primitive demonstrably handles invalidation and cleanup.

## Transport contracts and domain mapping

Must for correctness-sensitive requests; should otherwise. Typical severity: high/medium.

- Verify URL, method, params/payload, response envelope, status semantics, and identity dimensions from the API owner or generated schema. Confirm the actual endpoint and response shape before adding response unwrapping or shared adapters: read the call the component itself imports, because sibling components in one module routinely call different versions of the same resource, and the route a backend resource name suggests is not evidence of the endpoint in use.
- Before calling an endpoint replacement or migration compatible, compare the established and proposed contracts across actor/subject/tenant scope, route and version, request parameters or payload, pagination or complete-set semantics, response envelope, fields, nullability and ordering, authorization, privacy and errors, performance or query bounds, cache/refetch identity, and downstream consumers.
- Record intentional differences as explicit current-contract decisions and verify every affected consumer; do not infer full compatibility from only the fields one caller currently reads.
- Keep serialization, normalization, null/undefined/omission handling, and DTO-to-domain mapping in the API or boundary layer rather than spreading it through screens or feature owners.
- Do not add a generic unwrap, cache, retry, or error abstraction until multiple confirmed consumers share the same contract.
- Endpoint families that look similar may intentionally differ, including by provider or feature. Evolve each endpoint from its own schema and callers.

Suppress when an existing generated client or tested shared adapter already owns the transformation.

## Types, nullability, and casts

Should; must when authorization/privacy/request behavior changes. Typical severity: high/medium.

- Keep transport DTO, domain model, and display fallback distinct.
- Represent real nullability instead of casting it away. Apply `??` display fallback at the render boundary when the API value must remain nullable, and preserve API nullability with `| null` when real. Avoid `as`, `any`, or generic record escapes that hide a missing state.
- Use discriminated states or explicit fields when pending, empty, redacted, unavailable, failed, and complete have different behavior, and carry that distinction through mapping, storage, and display.
- Do not widen a domain object to `any`, generic records, or assertion-heavy shapes merely to satisfy one caller.
- Declare a type in the module's `types.ts`, not inside a component that state and other components import back. A type exported from a component file closes an import cycle the compiler accepts and the bundler initialises in an order neither file states.
- Model an absent id or reference as `null`/`undefined`, never `''`. An empty string is a `string` member and a falsy value, so `'' ?? fallback` keeps `''`, `typeof x === 'string'` passes, and a `.trim()` validator accepts it; only `null` and `undefined` are caught by `??` and `== null`.
- Write `field?: T` or `field: T | null`, never `field?: T | null`, unless the module can name the behaviour that distinguishes absent from null at that exact field. The three-state form matters at the wire: `JSON.stringify` drops an `undefined` key and emits a `null` one, which is leave-unchanged versus clear-the-reference in a PATCH body.
- Make a contract field required when every producer supplies it, and delete it when no consumer reads it. `?` removes the compiler's only enforcement point at the producer call site, so `openModal({ id })` type-checks with the payload key omitted; it also forces every consumer to branch on a state that cannot occur.
- Convert the operand before branching (`total !== 0`, `flag === true`, `array.length > 0`) and type flags as `boolean`. `![]` is `false`, `[] && <X/>` renders `0` as text, and `disabled?: boolean` makes `!disabled` and `disabled !== false` disagree about the pre-load state.
- For each `!`, `as`, or `as any`, name the claim the compiler rejects and resolve it at the source: widen or fix the upstream type, handle the reachable absence, or confirm the usage with the owning library. An assertion is erased at compile time, so it survives the type change that makes the value null and moves the failure to the first property access.
- Delete a `?? []`, `|| ''`, or `compact()` that sits above a proven guard, and handle the absence at the guard. A fallback re-declares the value as nullable to every later reader, and `?? []` allocates a fresh array so a consumer that compares by identity re-runs every render.
- Declare option and config arrays `as const` or as a string enum so the element type stays a literal union. Without it `{ value: string }[]` makes a `Record<typeof OPTIONS[number]['value'], X>` and a `switch` accept any string; fix exhaustiveness at the consumer instead of removing `as const`.
- Give an entity id one type across the module and make co-null fields share their nullability. `string | number` forces each consumer to choose between `==`, `===`, and `Map`/`includes`, so a dedupe or cache lookup misses for one source; when the defect is in a type, sweep every declaration of it in the same pass.
- When a body-level guard, typeguard, or redundant annotation exists only to satisfy a type the code owns, fix the declaration and delete the guard. A hand-narrowed signature such as `(selectedAll: boolean) => void` over `Dispatch<SetStateAction<boolean>>` is a second declaration of the same contract, and the two drift.
- Take an object parameter once a function has three or more positional arguments, especially when two of them share a type. `create(id, body, false, true)` is unreadable at the call site and reorderable with no error at all; a named object makes each value visible and the next parameter additive.

Suppress when generated types prove the narrower state impossible or a deliberate compatibility adapter is isolated and tested.

## Accessibility semantics

- Verify accessible name, label association, role, keyboard behavior, focus, disabled state, and semantic status — not only visual output.
- A missing label association or an unreachable control is semantic, not visual.
- Accessibility severity depends on supported workflow impact, not the number of ARIA attributes; the severity table in `references/review-rubric.md` decides the level, and a blocked essential workflow is graded there rather than here.

## Responsibility boundaries and delivery slices

Should. Typical severity: medium; low/preference when impact is only readability.

- Keep entry, route, and screen files focused on composition and orchestration.
- Put pure transformation, transport mapping, reusable UI sections, and lifecycle-specific effects in the narrowest independently testable owner.
- Extract only when a concern can evolve or be verified separately. Do not create one-use layers that only rename a call.
- Deliver separable behavior in bounded slices when dependencies and reviewability benefit; preserve the final integrated contract.
- Keep infrastructure, API wiring, UI behavior, cleanup, and broader regression work separate when each slice has a stable contract and independent value.
- Do not bundle an authorization change with a layout or behaviour change, or two halves whose module scope does not overlap, in one PR. Neither half can be reverted or bisected on its own: reverting the incident reverts the layout, and keeping the layout keeps the permission change. Suppress when the authorization change is what makes the new layout reachable, and say so.
- Avoid bundling speculative refactors into a behavior fix. Do not split tightly coupled behavior merely to reduce diff size, and do not accept an incomplete user contract because individual slices are tidy.

Suppress when extraction would split cohesive logic, conceal ordering, or create more indirection than ownership clarity.

## Memoization as a conditional tool

Prefer. Typical severity: low unless stale identity creates a real bug.

- Use `useMemo` for expensive derivation, copied/sorted arrays passed to memoized consumers, or a value whose stable identity is required.
- Use `useCallback` for an effect dependency, memoized child, or external subscription that requires a stable function.
- Keep ordinary handlers and cheap expressions plain. Use `useMemo` and `useCallback` only for demonstrated cost or identity contracts; optimization style alone is non-blocking.
- A missing or extra memoization helper is not a finding without a concrete identity, stale closure, or measured cost consequence.

## Test-authoring quality

Tests should encode why the behavior matters and fail when that behavior regresses.

- Prefer observable assertions over implementation surveillance. Assert behavior that would regress: exact request, mapped data, visible state, emitted action/event, navigation, persistence, or cleanup.
- Assert at the seam the change owns. When the diff changes only a value the module hands to a shared mechanism — a message, a request payload field, an event name — assert that value at the boundary and stop: re-rendering the mechanism's output proves a component the change does not own and couples the spec to its DOM. Require the rendered form only when the change alters whether, where, or when the value reaches the screen.
- Do not assert behavior the implementation does not specify. An assertion over an accident pins it into the contract, so the fix that removes the accident breaks a test that never described a requirement.
- Add the smallest assertion set that proves the regression. One exact assertion can be enough; a second is useful only when it proves a distinct contract. An assertion count, snapshot, or mocked hook call is supporting evidence, not a substitute for behavior the change produces; where the mocked call's argument is itself the changed contract, that assertion is the contract.
- Assert every payload key that drives a downstream effect. A test that sets a value but asserts only a sibling key lets a dropped key pass silently; assert the exact body the consumer depends on.
- Assert the request through the repository's established transport mock, `fetchMock` in these apps, instead of adding a second mocking layer for one suite. Two transports in one repository mean one of them does not describe the shape production sends.
- Cover the absent/legacy state explicitly. When a value can be `null` (a request predating the field, an unanswered question), add a test that leaves it unset and asserts the guard fires — the missing-state case is where gates silently fail to block.
- Test unauthorized/unknown separately from loading when their behavior differs.
- For every value newly added to a status, type, flag, or bound guard, add a case whose input is exactly that value plus one that fails the guard. Every pre-existing fixture satisfies the old condition, so narrowing to `includes(status)` or threading `true` through the setup leaves the new arm unexecuted by construction.
- When a behaviour is corrected, add a case that fails on the parent revision and leave the old expectation alone. Editing it rewrites the oracle to whatever the new code does, so it distinguishes neither the old defect nor a future regression.
- Hardcode the expected output (`'1.57 weeks'`, `6`, `'Jan 09, Jan 23'`) instead of recomputing it with the same helper, `Intl` call, or factory under test. An oracle built from production code agrees with itself by construction.
- Keep arrange, act, and assert visible inside each `it`. Share data factories and the provider wrapper, not the act or the expectation, and reuse the wrapper the file already has rather than a second one with its own provider list: a helper that clicks and asserts moves the failure to its own line, and the next author relaxes it to make a new case pass.
- A unit test can be sufficient for a pure transform. Integration or E2E is justified when a real boundary is otherwise replaced. More tests are not automatically better: ask which changed behavior remains unproved.

## Test assertions (org rules)

- Assert visibility with the surface's own matchers: mobile uses `toBeVisible` for presence and `not.toBeOnTheScreen` for absence, web uses `toBeVisible` for presence and `not.toBeInTheDocument` for absence. `toBeDefined`, `toBeTruthy`, and `toBeInTheDocument` pass for a node that is mounted but hidden, so they do not prove visibility.

## Mocks, fixtures, and dynamic E2E data

- Match the production boundary and real response shape. Do not mock away the boundary under review, and prefer the real child component where the mock would remove the integration the test exists to prove: if mapping is the contract, feed the real mapper a transport-shaped response.
- Keep fixtures scoped to the case and minimal; avoid global defaults that accidentally authorize every test.
- Reset timers, handlers, network mocks, storage, and subscriptions owned by the test.
- A mocked passing test cannot prove the mock matches production. Inspect the boundary shape.
- Drive a selector from the store fixture passed to the render helper instead of `jest.spyOn(selectors, ...)`: with `restoreMocks` off, a spy installed in `beforeEach` keeps returning its stubbed value for the rest of the file, so the case whose whole point is the flag-off path runs with the flag on. Mocking transport, router, analytics, and remote-config values is expected and unaffected.
- With `jest.useFakeTimers()`, advance exactly the owned interval and assert the call count inside the loop; never mix a real `setTimeout` or `waitFor` into a fake-timer test. `runAllTimers()` drains the poll scheduled from inside the callback, so "polls every N ms and stops after M attempts" collapses into "polled at least once", which any implementation satisfies.
- Deterministic debounce substitution is acceptable when timing itself is not the contract.
- Dynamic E2E fixtures must be idempotent, self-contained, self-cleaning, and safe to rerun: generate a unique marker owned by the case; discover or create only data bearing that marker; make setup safe after a previous interrupted run; assert the intended UI/API behavior; clean up by independently reading back marker-owned records; verify cleanup rather than trusting the delete call; never delete by a broad tenant, date, name, or unresolved variable; and document explicit country, provider, permission, or platform skips.
- Use deterministic waits on visible/API state, not fixed sleeps.
- An exact test selector is version/component-scoped, not a global convention.

## Evidence, CI, and delivery claims

Must when enforced; must for external review claims; contextual otherwise.

- Use the target repository's current Node/Yarn/wrapper, generated metadata, CODEOWNERS, changeset, platform build, and validation conventions. Repository gates are repository rules, not stylistic preferences.
- Run `git diff --check` when appropriate.
- Distinguish a source change, green CI, merged PR, deployed revision, and exercised runtime. None substitutes automatically for the next layer. Green CI proves named jobs at a revision, not deployment or runtime; merge status proves ancestry, not integrated behavior.
- Keep shared-resource or stacked delivery boundaries explicit and verify the final integrated state. For a stacked branch, prove the base is included before reviewing: `git merge-base --is-ancestor <base head> origin/<branch>` and `git ls-tree -r --name-only origin/<branch> | grep <feature file>`. Without that, a missing commit and a missing feature look identical and the wrong one gets reported.
- Keep the reviewed head append-only while threads are open. GitHub anchors an inline thread to a blob sha, so a force-push or rebase collapses every thread to outdated and loses the mapping from a finding to the line that fixed it. Re-run a checkbox-triggered CI gate after any push before citing it as green.
- An authored change is evidence of implementation behaviour, not of a team standard. Current target source and tests override patterns from an older revision.
- Record the exact head and note unavailable runtime/platform/deployment evidence.
- A pattern observed once inside a migration context does not become a rule for the next change. Inspect the surrounding code, the date, and the current contract.

### Evidence layers

Report these separately:

| Layer | What it proves |
|---|---|
| Source | The inspected revision contains the code |
| Static validation | Types/lint/build rules accept the inspected scope |
| Unit/component test | Behavior under test doubles and represented state |
| Integration/E2E | Boundaries exercised in the named test environment |
| CI | Named jobs passed for an exact revision |
| Merge | Revision entered the target branch |
| Deployment | Exact artifact/revision was deployed to a named environment |
| Runtime | Named user/API/device path produced the observed result |

Never silently promote evidence to a later layer.

### Evidence suppressions

Do not demand:

- a broad E2E suite when a focused test fully proves a pure change;
- every failure presentation in one PR when the task intentionally delivers a bounded slice and the critical path remains safe;
- iOS proof for an Android-only supported change or the reverse;
- runtime claims when runtime access was unavailable.

Instead, state the unverified boundary and its consequence for confidence.

## Locale files

- Never read a locale file in full; search for the specific keys the change touches. A catalogue such as `en-AU.json` runs to megabytes, so a full read costs the pass its attention and returns nothing a key search would not.

## Conventions

### Naming should expose domain meaning

Should. Confidence: medium. Typical severity: low/medium only when ambiguity can cause misuse.

- Prefer names that identify the domain value, state, or side effect rather than generic containers such as `data`, `item`, `value`, or `handleThing`.
- Distinguish transport, normalized, selected, draft, and display values in names when they coexist.
- Name booleans as conditions and functions as actions or questions.
- Justify a rename by the wrong thing the current name made a reader assume or made the call site do, then propose the name that removes that reading. A comment that restates a fact the name already carries is the defect a rename removes.

Suppress when the surrounding module already establishes meaning, a short callback parameter is conventional, or renaming would create churn without improving the reviewed code.

### Optimize for direct readability

Prefer. Confidence: medium. Typical severity: low/non-blocking.

- Favor direct control flow over nested ternaries, clever coercion, and wrappers that obscure a single operation.
- Keep related logic close enough to understand its sequence.
- Prefer an explicit condition when implicit truthiness hides meaningful `0`, empty, null, or false states.

Do not flatten domain boundaries or reject a well-established repository abstraction in the name of simplicity.

### Comments should explain non-obvious intent

Prefer. Confidence: low/medium. Typical severity: none/low.

- Retain comments that explain a compatibility constraint, counterintuitive dependency, security boundary, or temporary migration reason.
- Remove or avoid comments that merely narrate the next line and can be replaced by a clearer name.

Do not comment on comment style alone unless misleading documentation creates a concrete maintenance risk. Tooling/API comments may be repository-required.

### Written feedback conventions

Applies to the reviewer, not the submitted code.

- Point to the smallest owning location.
- Explain the triggering condition and consequence.
- Ask a focused question when the contract is uncertain.
- Suggest the smallest direction that resolves the issue rather than rewriting the feature.
- Separate blocking correctness from optional improvement.
- Write the register into the comment: `optional:`, `can be addressed in another PR`, `we can keep this as is because <reason>`, `100% not recommend`. An unmarked comment reads as a requirement, and a soft marker with no condition reads as closed, so a deferral names the condition that reopens it. This is a register requirement, not a tone formula.
- When a statement in the thread is wrong, answer it with the mechanism that makes it false and ask for the specific case that would make it true; hold firm only where the consequence is safety, security, or process. Naming the mechanism gives the author something to check against the code rather than against the reviewer.
- When asking for a reuse or theme-scale change, name the existing primitive, show the two-to-five-line before and after, and say that the pattern must be swept across the PR; an illustrative single line is not the request. Drop the sweep clause when the pattern occurs once.

### Resolve feedback with explicit disposition

Should. Confidence: medium/high.

For each review thread, classify it as fixed, answered, stale, intentionally deferred, user-skipped, or no action. A code change without a clear disposition can leave the actual concern unresolved.

## Gotchas and counterexamples

### Authorization and privacy

- A hidden button is not authorization, but its presence is not automatically exploitable. Trace the server/action boundary.
- A feature flag may be an intentional rollout or compatibility signal. Do not demand fail-closed UI if current product behavior explicitly permits unknown/loading/legacy states and no protected action fires.
- Not every personal-looking field is classified sensitive. Confirm the endpoint/domain classification.
- A redacted display does not prove the transport is safe; conversely, a raw transport field is not necessarily exposed if the authoritative server contract classifies and restricts it. Verify both layers.

### Types and nullability

- `null`, `undefined`, omission, empty string, and empty array are not interchangeable. The endpoint contract decides.
- A display fallback such as `value ?? '—'` belongs at rendering and does not justify erasing transport nullability.
- A type assertion is not automatically wrong when it isolates a verified third-party/generated gap. Flag it only when it hides a reachable state or spreads unsafety.

### Architecture and state

- "Thin components" is not a file-size rule. Cohesive logic may be clearer inline.
- One call site does not justify a shared abstraction. Multiple call sites do not prove identical contracts.
- `useMemo`/`useCallback` are not mandatory style. Require cost, stable identity, or dependency correctness.
- A missing effect dependency is not a finding if the value is provably immutable or deliberately captured and documented/tested.
- Component state is not always wrong for server-derived values; an explicit editable draft can legitimately diverge.
- Not every `.map()` needs virtualization. Require realistic list size or a current list contract.

### Navigation

- Navigation actions are semantic: `navigate`, `push`, `replace`, and reset are not stylistic substitutes.

### API and caching

- Similar endpoints can use different versions, envelopes, nullability, filters, and error semantics.
- Compatibility describes the observable contract, not identical internal implementation. Suppress a parity finding when current evidence proves that an intentional difference is accepted, bounded, and safe for every affected consumer; do not infer compatibility only from the fields a current caller destructures.
- Do not introduce generic unwrapping, retry, or cache rules from one endpoint.
- A successful response is not proof of the downstream effect, and client cache invalidation is not automatically necessary when the owning query key or server push contract handles freshness.

### Tests

- More tests are not automatically better. Ask which changed behavior remains unproved.
- A mocked passing test cannot prove the mock matches production.

### Delivery

- Repository commands, Node/Yarn versions, changesets, CODEOWNERS, and branch rules can change. Read current instructions.
- Green CI proves named jobs at a revision, not deployment or runtime.
- Merge status proves ancestry, not integrated behavior.
- An authored PR demonstrates what that author implemented in that context; it does not prove what the team would demand in every review.
- A repeated comment can still be migration-specific. Inspect surrounding code, date, and current contract.

### Severity traps

- Do not assign high severity to a stylistic preference because it was stated emphatically.
- Do not assign critical severity to a client-only guard omission without a reachable protected backend effect.
- Do not downgrade a real data/privacy issue because the patch is small.
- Do not convert missing runtime evidence into a code defect; state the evidence gap.
- Do not report unchanged debt unless the change newly exposes it or explicitly owns its removal.

### Suppression questions

Before publishing any finding, ask:

1. Is this required by current source/contract or only historical preference?
2. Is the affected path supported and reachable?
3. Does another owner already enforce the condition?
4. Is this a deliberate compatibility/migration/platform exception?
5. Does a focused test prove the behavior is intentional?
6. Did the target move after the evidence was gathered?
7. Would the suggested fix expand scope or break a sibling contract?

If unresolved, lower confidence, ask a focused question, or suppress the finding.
