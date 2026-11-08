# Review rubric

The decision procedure for a pass: how to scope it, how to validate a candidate finding, how to grade it, what posture to recommend, and how much weight the evidence carries. It is not a checklist that needs one comment per category.

## Scope and freshness

Record, before findings:

- repository and package;
- the base and the exact head commit;
- the changed files, and the user-visible or developer-visible path each affects;
- the applicable `AGENTS.md`, package guidance, API schema, and ticket or pull-request contract;
- whether evidence is source-only, test-backed, CI-backed, deployed, or runtime-observed.

Without an immutable repository, base, head, and changed-file set, return a scope-unresolved result rather than findings or an approval. If the target moves after analysis, invalidate the affected findings and refresh before the decision, and again before any write. A plan-only review pins the current baseline and reports proposed design risks, not defects in unwritten code.

## Map the changed contract

For each material change, answer:

- Who owns the decision: server, transport or DTO mapper, state owner, route, component, storage layer, or test fixture?
- What are the meaningful states, including unknown, loading, empty, partial, unauthorized, error, retry, and stale identity?
- Which identifier controls tenant, member, or organisation context?
- Which caller and downstream consumer rely on the changed shape or side effect?
- Which platform, provider, locale, feature flag, permission, or migration state narrows the contract?
- Is that exact state supported today, intentionally excluded, or newly exposed by this change?

Do not review a patch fragment in isolation when its correctness depends on an adjacent owner.

## High-signal passes

### Correctness and data

- Check branch conditions, transformations, null, undefined and omission semantics, stable identifiers, deduplication, ordering, and mutation outcomes.
- Verify request URL, method, params and payload, response shape, mapper, cache key, invalidation, and rendered use.
- Confirm that explicit error and readiness states are neither silently converted to success nor left loading forever.

### Authorization, privacy, and identity

- Trace the authoritative server or action boundary before treating a flag, menu, route guard, or client state as authorization.
- Verify that sensitive fields are projected or redacted by the owning contract and are not reconstructed from raw client data.
- Include every identity dimension that can change the result, and confirm reset or invalidation on identity transitions.
- Treat credible cross-tenant access or raw sensitive-data exposure as critical; a UI-only presentation discrepancy is lower.

### Architecture and maintainability

- Keep route and entry files as composition boundaries, and domain behaviour in the narrowest owner.
- Reject an abstraction with one speculative consumer, and a wrapper that conceals the real transport or lifecycle contract.
- Check the registration and ownership surfaces: route, reducer or store, effect, provider, navigation root, background handler, `CODEOWNERS`, and release metadata where applicable.
- Prefer explicit domain types over casts and widened generic containers.

### UI and lifecycle

- Check stale closures, dependency identities, premature effects, duplicated state, wrong remount assumptions, and accessibility semantics.
- Verify behaviour on the platform and navigation lifecycle the change supports, not an imagined web unmount model.
- Treat optimization helpers as conditional tools: require a real identity, dependency, or cost reason.

### Tests

- When behaviour-bearing changed code lacks owning coverage, require focused assertions on observable behaviour: request contract, visible state, emitted event, persistence, navigation, or cleanup.
- Do not demand duplicate coverage for docs and configuration, for a pure transform already proved at its owner, or for an unchanged shared boundary.
- Check that mocks preserve the boundary under test and do not encode impossible production shapes.
- Dynamic end-to-end data must be marker-owned, idempotent, independently cleaned up, and scoped to the tested tenant, provider, and platform.

## Validate a candidate finding

Fill this record before reporting. A missing field turns the finding into a conditional question or an evidence gap, not a defect.

| Field | Required content |
|---|---|
| Location | Smallest changed line or symbol that owns the defect |
| Trigger | Specific input, state, timing, platform, or caller |
| Path | Reachable sequence from the change to the consequence |
| Expected | Current authoritative contract |
| Observed | What this code does under the trigger |
| Impact | User, data, security, release, or maintenance consequence |
| Evidence | Source, test, or runtime proof, with its freshness |
| Suppressions checked | Guards, callers, tests, generated types, migration exceptions |
| Correction | Smallest contract-aligned direction, not an unsolicited redesign |

Suppress the finding completely when current evidence disproves reachability. Treat missing evidence as approval-blocking only when a named acceptance or repository gate requires it. For a latent defect made newly reachable, locate the changed reachability edge and cite the unchanged callee as downstream evidence; suppress when no changed edge or ownership link exists.

## Severity

Severity follows impact and reachability, never rhetorical strength.

A domain reference may state a typical band beside the rule it carries, and several do. The band orients the grade and never decides it: where a band and this table disagree, the table decides and the review says which one it applied. A band that reads "critical/high for reachable access" is the common case, because reachability alone settles High and leaves Critical to the confirmed raw exposure or cross-tenant operation named below.

| Level | Use when | Do not use when |
|---|---|---|
| Critical | Confirmed raw protected-data exposure, unauthorized cross-tenant operation, or broad destructive corruption | A flag or UI guard is merely missing without an exploitable backend path |
| High | A supported path produces a bounded privacy or authorization failure, wrong mutation or data, data loss, an indefinite critical flow, or a named current gate blocks or misroutes release | Only optional cleanup, taste, an unproven migration risk, or a non-blocking process omission exists |
| Medium | A bounded functional, accessibility, lifecycle, performance, test, or maintainability failure | Tooling prevents it automatically, or the impact is hypothetical |
| Low | A concrete, narrow, non-blocking issue worth fixing | Personal wording or a stylistic preference alone |

Confidence is separate from severity. A high-impact hypothesis with incomplete reachability is not yet a high-severity finding.

## Decision posture

- `request changes`: at least one validated critical or high issue, or a concrete medium issue that violates the acceptance contract.
- `comment`: an actionable medium or low issue, a conditional evidence question, or a scoped preference that benefits from discussion.
- `approve`: no validated blocking issue at the pinned head; state the remaining evidence limits.

These are recommendations until the operator authorizes the write. Posting, requesting changes, and approving are all writes, and each needs a refresh of the head, the threads, and the checks immediately before execution.

## Evidence authority

Current target code, tests, product contracts, security rules, API schemas, repository instructions, and verified runtime behaviour outrank any guidance in this skill.

- A repository pin or a historical implementation establishes what was inspected at that point; refresh exact tool, API, component, and wiring claims against the current target before reporting a defect.
- A green test, build, merge, or deployment proves only its own layer. Do not infer device, browser, tenant, provider, or production behaviour without proof at that boundary.
- Keep the evidence classes apart when deciding whether a rule applies: repository contract at a known revision; implementation patterns that corroborate a rule without proving it universal; counterexamples that narrow a broad rule and supply suppressions to check; runtime or deployment evidence that applies only to the environment, revision, identity, platform, and path actually exercised.
- A delegate's finding is a candidate, not evidence. It enters the report only after you reproduce its quoted line at the head commit yourself, and the delegate's stated confidence is not the finding's confidence.

## Confidence and applicability

- A rule stated as must or should still requires a supported reachable path, a current contract, an observable consequence, and checked suppressions.
- A rule stated as prefer guides readability or design; do not report it as a defect without a concrete contract or consequence.
- Fixed tone formulas, universal memoization requirements, unconditional mobile navigation rules, and mandatory migration sequences are not implied by anything here.
- When applicability is uncertain, lower the confidence, ask one focused question, or suppress the finding.
