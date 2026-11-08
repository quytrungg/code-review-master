# Mobile Review Rules

These rules apply to the React Native app only, and are read after the shared frontend rules. They cover feature and module ownership, navigation and lifecycle, API and domain mapping through the module's own owners, mobile UI and localization gates, critical-path network behavior, headless/background/persistence/offline work, platform and device boundaries, list performance, and the evidence each mobile layer requires. Authorization, data-fetching state, types, test-authoring quality, evidence layers, and naming conventions live in the shared file and are not repeated here.

## Feature and module ownership

- Read the owning `MODULE.md` before changing a module. For modularized work, preserve its module-guidance section, state-management/pattern era, Squad, co-ownership, and registration gates. New modules belong under `app/modules/`; do not mechanically move legacy `app/components/` modules.
- Reuse established app-shell and feature-module boundaries. Do not introduce a parallel store/client/provider for one screen without a contract gap.
- Thin-entry guidance is a preference until complexity or ownership creates a concrete defect.
- Use explicit feature contracts and serializable route params. For new deep-linkable, persisted, or cross-stack routes, do not pass service instances, callbacks, or large mutable domain objects through navigation state. Suppress this concern for a component-scoped, non-persisted callback when the installed navigation contract explicitly supports it.

## Navigation and lifecycle

- For a new route stack, follow the current typed route contract: in-file route constants, a typed stack-param list, `NavigatorScreenParams` for nesting, typed native stacks, separate sub-stacks, and route-stack tests where current instructions require them. Treat legacy route-action helpers as legacy unless the owning module documents otherwise.
- Verify route/deep-link inputs against the destination's current organization/member/tenant context when those inputs can outlive or cross identity state. This is a general identity-boundary check, not a universal claim that every deep link requires a new validator.
- React Navigation keeps a screen mounted after the user leaves it, so use the screen's focus, blur, and unmount contract for listeners, timers, requests, and one-shot behavior instead of assuming a mount.
- Avoid duplicate navigation or effects caused by repeated focus, remount, or callback identity changes.
- Make an effect that navigates or resets on a success value idempotent per mount: fire the reset in the same handler so the guard flips before a second call can re-run the effect, and keep per-render values such as `navigation` and inline handlers out of its dependencies. Cleanup does not save it, because `navigate` is not a guaranteed unmount.
- Before accepting a hardcoded `goBack()` or `pop(n)`, count the stack depth for every entry path into the screen and prefer navigating by route name. `pop(2)` returns to the roster tabs from the tab flow and somewhere else when the same screen is reached from a deep link or a notification.
- Open a pre-filled screen from serializable route params or form `initialValues`; do not stage values in Redux on the previous screen or call `change(FORM, field, value)` from an effect, which runs after redux-form initialises and races the user's first edit.
- For deep-link work, verify the current app scheme/host, root navigation tree, and destination context. Do not copy frozen scheme values into a finding without checking current configuration.

Severity comes from the table in `references/review-rubric.md`; a reachable cross-tenant read or mutation, and wrong-identity navigation, are graded there rather than here.

## API and domain mapping

- Follow the current module owner. React Query hooks under `app/hooks/api/` own ordinary API calls, Redux plus persistence owns established cross-component/offline state, legacy `redux-api-call` stays legacy-only, and epics are for complex orchestration rather than new API calls.
- An inline request inside a component moves to the module's hook owner. A component that builds its own URL and dispatches its own fetch carries request state, error mapping, and a cache key that no other screen can reuse or invalidate.
- Confirm which serializer the client route actually mounts before claiming a field is missing: one model is frequently serialised by several (`MinimalLeaveCategorySerializer` on the member route, `LeaveCategorySerializer` elsewhere) and only the mounted one decides the payload.
- Preserve the current query subscription contract; avoid transformations such as broad object-rest destructuring when they subscribe callers to every changing field.
- Put a hook another screen consumes in the module's hooks owner, not inside a component file. Its callers then import a hook rather than a component boundary, and the hook stays testable without mounting the screen that happened to declare it.
- Derive store state with `createSelector`; `flow` composition has no cache, so it returns a new object or array on every store change. A parameterised lookup belongs in a `xxxSelectorCreator(id)` rather than in a selector that takes a second argument, because a fresh argument defeats the last-result cache and an inline call creates a new selector instance per render.
- Select clocking flavour, leave-balance source, and tab set from the permission or menu payload (`hrpr_swag.features`, menu customisation, the `...PermissionSelector`), never from `currentLoginProvider`: that selector reports how the member authenticated, not which product surfaces the member is entitled to. An HR+PR account can hold both permissions and still have `leave: false` in menu customisation.
- Return `null` and render nothing when a derived value is invalid. `moment(null)` yields today, `Date.parse('')` yields `NaN` that makes every comparison false so a guard reads as allowed, and `isValid ? units : 0` renders a zero amount for an unfinished range.

## UI and localization

- `@hero-design/rn` is required for UI, and localization for all user-facing text. Treat these as repository gates, not stylistic preferences, while preserving documented legacy/module exceptions.
- Follow installed Hero and ESLint contracts for styling, imports, immutability, and React Compiler compatibility; do not enforce a historical component recipe after the dependency changes.
- Any UI change requires manual verification on both iOS and Android. Keep the observed results platform-specific. Suppress the second-platform gate only when current task/repository scope explicitly establishes a non-UI or unsupported-platform exception.
- Before reporting a greyed control as visual-only, read what actually renders it. React Native's `TouchableOpacity` given `disabled` does block the press, so a control that still fires means the disabled value and the visual intent come from different expressions, or a press handler re-implements the guard and omits it; a `styled(TouchableOpacity)` receiving the same boolean is not a defect.
- When a guard reads a field off the selected form object, check how edit mode seeds that object. A screen whose initial values are built from an API payload (`getInitialValues`) carries only the fields it copies, so a category- or entity-level flag read from the form is absent, or false by default, in edit while present in create. Prefer the selector that resolves the id against the fetched list, and ask for a test seeded with the edit shape rather than the create shape.
- Flag a changed user-visible default, a number's precision, or whether a control looks disabled as a product change needing PO or design confirmation, even when the new behaviour is technically equivalent. `toFixed(2)` becoming `toFixed(1)`, a dropped pre-selected date, and a grey-but-tappable button each change what the member sees or can do, while the ticket usually covers only the refactor.

## Critical-path network behavior

- A nonessential request must not indefinitely block the critical screen or silently convert its own failure into success for the whole flow.
- Bound retry, waiting, and loading behavior when the current product contract defines a limit or recovery path.
- Do not make "every network request needs a timeout/retry" a universal finding. Require a demonstrated critical-path stall or existing repository contract.

## Headless, background, persistence, and offline

- Headless/background code must not depend on React hooks, mounted providers, navigation state, or UI-only lifecycle.
- Use the actual module's approved persistence boundary for protected durable data; verify encryption requirements, key ownership, migration, organization scoping, and cleanup. Do not prescribe MMKV, encrypted storage, Redux Persist, SQLite, or another library universally.
- Offline replay requires more than a queue helper. Trace root registration, enqueue, persistence, connectivity/process restart, replay, deduplication/idempotency, success removal, terminal failure, retry/backoff, and user-visible recovery when specified.
- Never infer that an offline path is complete because types, storage, or unit tests exist.
- Before claiming a known replay-wiring gap, refresh the final target head.

Missing headless registration or replay handling is high only when the supported shipped path relies on it; incomplete speculative scaffolding can be medium or suppressed.

## Platform and device boundaries

- Android evidence proves Android only; iOS evidence proves iOS only. Simulator/emulator and physical-device evidence are not interchangeable when notifications, background execution, biometrics, secure storage, or OS lifecycle matter.
- Inspect native configuration, permissions, entitlements, manifests, app state transitions, and platform-specific code for the changed path.
- Keep platform branches explicit and test the supported matrix. Do not demand unsupported parity.
- Hoist `Platform.OS` ternaries into module constants or `.ios.tsx`/`.android.tsx` files: each platform ships its own bundle, so the check is a build-time literal and a ternary inside a component re-evaluates a constant per render. Where the real difference is in the value's shape, such as a picker URI that may already carry `file://`, branch on the value instead of encoding an assumption about the platform.
- Source and Jest evidence cannot establish device/runtime behavior by themselves.

## Lists and performance

- Route list changes through the current `FlatList`/`SectionList` contract for large or incrementally loaded collections. Use stable `keyExtractor` behavior and `getItemLayout` where fixed layout and current guidance make it applicable; document variable-height or legacy exceptions.
- Preserve stable keys and do not nest virtualized lists in scroll containers that defeat virtualization.
- Declare a regex, options array, or style object outside the component. A literal rebuilt on every render is a new reference for each child, memo comparison, and effect dependency that reads it, so a list re-renders for a value that never changed.
- Require realistic scale, rerender cost, memory impact, or an established list contract before treating a list as a performance defect.

## Mobile tests and evidence

- For lifecycle behavior, exercise focus/blur/remount/process boundaries represented by the production owner rather than shallowly invoking a callback.
- For offline behavior, cover enqueue, durable readback, replay registration, idempotency/deduplication, success removal, and failure/retry branches required by scope.
- Exercise a permission or feature gate through its real hook; a `jest.mock` of the gate the PR just introduced leaves the fetch-and-decide logic unexecuted. Give each side of a boolean-swapped pair its own marker instead of one `testID` attached after the swap, because a query on that id passes for both implementations.
- Maestro/dynamic E2E fixtures must use unique markers, be safe to rerun, read back cleanup independently, and state provider/country/platform skips explicitly.
- Keep platform claims aligned with the test matrix. An Android-only offline suite does not prove iOS.
- Jest proves JavaScript behavior under represented lifecycle/platform mocks. A native build proves compilation/linking, not runtime background behavior. Simulator/emulator evidence proves that platform/runtime combination. Physical-device evidence is required when the contract depends on OS scheduling, push, biometrics, secure storage, or hardware behavior not faithfully simulated.
- For offline replay, evidence should identify which of these were exercised: enqueue, persistence, process restart, root registration, connectivity restoration, replay, idempotency, success removal, terminal failure, retry/backoff, and UI recovery. Do not label the feature verified when the required chain has gaps.

## Mobile validation and delivery

Use the current package commands, `MODULE.md`, and package conventions. For Work-app feature work, verify the real app shell/product flow, not a standalone imitation. The root toolchain declares Corepack/Yarn 4.13.0 and Node 20.19.4+ plus native Ruby/Xcode/JDK prerequisites; refresh package instructions before running or enforcing exact versions.

Current repository gates can strengthen the generic "smallest relevant test" rule. Check the owning module and change class for required unit, stateful-component integration, module-flow E2E, key payroll/core-HR smoke, both-platform UI, route-stack, ownership-generation/module-scan, dependency-singleton, and native-build evidence. Do not waive a named current gate merely because one focused test passes, and do not demand unrelated suites outside the owning contract.

Evidence for these comes from the pipeline and the device, not from this review:

- focused Jest results and scoped ESLint are CI's, read from the head's own check run;
- the relevant package type-check is a pipeline result, read the same way;
- Android/iOS build or device evidence is read when the changed native/runtime boundary requires it.

For large changes, check the current PR-size and squad presentation gate; treat it as repository process, not an automatic architecture defect.

- Report tests, platforms, devices, runtimes, and skipped evidence separately. Do not equate green JavaScript tests with a verified background or native integration.
- Read suite and test counts from the head's own check run, beside the head sha, rather than running the suites here. A pipeline that runs type-check only leaves the tests unproven, so a green PR is not test evidence.
