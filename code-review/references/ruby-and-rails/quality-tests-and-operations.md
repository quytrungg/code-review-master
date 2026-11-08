# Quality, tests and operations

## Boundaries, service objects, and reviewability

- Follow established repository and domain boundaries. Service objects are useful when they provide a clear home for orchestrated business logic; they are not mandatory, and extracting a single-use class is not inherently better.
- Treat a sibling endpoint of the same family as the contract when one member diverges. `table_metadata`, the index and create actions all resolved an optional `payroll_info_id` through the same `hr_payroll_info` helper while `field_metadata` ignored the payroll profile, and the divergence was the defect rather than a special case: the sibling's helper already falls back when the parameter is absent, so the added input breaks no caller. Read the sibling before accepting a justification of the difference, and suppress when the sibling's parameter belongs to an unlanded change.
- Keep workers thin when business logic has a reusable domain boundary or needs isolated tests; do not create a service object solely to satisfy a pattern. Name concepts consistently across requirements, schema, APIs, code, events, and UI, and distinguish genuinely different domain terms rather than normalizing them cosmetically.
- Treat broad changes as a reviewability signal. File count alone is not a defect; ask whether independent risks can be verified and deployed separately.
- Extract constants when a value is reused, conveys domain meaning, or is configurable; do not report every literal as a finding.
- Remove dead code only with evidence. Reflection, callbacks, schedules, configuration, external invocation, and plugins can hide usage, so combine static and runtime evidence with code-owner confirmation for risky deletion.

## Error handling and rescue boundaries

- Rescue expected exceptions at the boundary that can handle them; a process boundary records context and re-raises, routes, retries, dead-letters, or returns a documented fallback. The Error handling section below is the full rule.
- A rescue that makes a remote write non-blocking must not also wrap the file flush and fsync that precede it. A checkpoint or upload helper that starts with the writer's `sync!` and then reads the file puts durability failures inside a `rescue StandardError` labelled for the remote service, so a failed fsync is logged as an upload failure while the run still reports success. Call the sync before entering the rescued region; the helper's own comment is the check, because a comment naming only the remote failure describes a narrower rescue than the code has.
- When rewriting error handling, carry forward the failure reporting the old path had, and never let ensure or cleanup code mask the original exception. A rewrite that drops an existing `rescue => e; BugReporter.notify(e)` converts a reported failure into a silent one, and cleanup that touches an uninitialised variable raises over the real exception.
- Prefer the simplest implementation that preserves the contract. Complexity findings must name the concrete failure mode, not merely count branches or classes.

## Callbacks, configuration, and dependencies

- Keep changelogs, generated schemas, compatibility notes, and operational documentation synchronized when the contract actually changes.
- A comment or doc block that describes the condition a change modifies is part of the change. `effective_position` kept the comment "Flag on: fall back to the requisition's position" after the method began requiring `position_based_management` as well, so the next reader trusts a gate the code no longer has. Diff every adjacent comment and doc paragraph against the predicate it describes, and suppress when the comment records why the gate exists historically rather than what it currently requires.
- An externally visible parameter or response change also changes the API blueprint. `doc/api_v4.apib` carries each v4 endpoint, and a new optional `payroll_info_id` that appears only in the serializer leaves API consumers unable to discover it or to learn that an unknown id answers 404; the sibling endpoint's section holds the form to match, `+ payroll_info_id: 1 (integer, optional)` plus its paragraph. The blueprint is usually absent from the changed-file set, so read it at the head rather than trusting `--json files`. Suppress for an internal-only parameter.
- Active Record callbacks must be free of external side effects: an `after_commit` email or webhook fires unintentionally during console data fixes and ad-hoc updates. Put side effects explicitly inside service objects, outside the Active Record lifecycle.
- Integration clients need a dedicated error class so callers can rescue without catching unrelated `StandardError`s; a wrapper that raises bare StandardError with different messages per error code forces callers to rescue everything.
- Configuration values memoized at boot make test and stub environments awkward; prefer lazy readers so specs can stub `ENV` values.
- Use `ENV.fetch` without a default for mandatory configuration and with an explicit default for optional configuration, unless the repository's typed configuration layer provides the contract. Validate configuration at boot when late discovery would make the service unsafe or unavailable, and do not print secret values while diagnosing failures.
- Before adding a dependency, inspect existing solutions and compare maintenance, security, compatibility, memory, CPU, latency, and ownership. A public gem is not automatically better than in-repo code, or vice versa.
- For a dependency on a core path, check release activity, maintainership, migration strategy, and exit cost.
- Preserve backward compatibility across defaults and all consumers when changing shared gems, serializers, producers, or clients.
- Keep ISO 8601 as an external serialization expectation where the API contract requires it; it is not a rule for typed database storage.

## Test authoring

- Add tests for new behavior at the level that can fail when the business contract changes; a test that only proves code runs is not enough.
- A scope guard added for one paradigm or org type needs an example that fails when the guard is deleted. `return unless %i[hr_only hr_py]` gated the payroll-profile lookup, and the 404 spec ran only under a stubbed paradigm, so removing that line makes every AIO organisation answer 404 while the suite stays green. Ask for the guard's own example, modelled on the sibling spec's foreign-id context that expects 200, and name the line whose deletion nothing would notice.
- Restore global state changed by specs: environment variables, constants, feature flags, time, caches, class attributes, global registries, and connection configuration.
- Positively prove that the intended record or job traversed the expected path. Absence from the source queue and absence from a dead set can both be true after silent loss; use a run-specific identifier and assert the destination or consumption result.
- Exercise negative authorization, retry exhaustion, partial completion, duplicate delivery, concurrency, and rollback paths when those risks exist.
- For migrations, read the generated schema and SQL the change produces — the regenerated `schema.rb` in the diff and the pipeline's own consistency check — rather than running the migration here. Require rollback proof only where the operational contract supports it. Require staging or runtime evidence only when behavior cannot be established from source and CI; screenshots are supporting evidence, not a universal completion requirement.

## Performance evidence

- Benchmark representative hot paths when changing serializers, protobuf conversion, caching, dependencies, or high-volume loops, and record the workload and comparison baseline.
- Match evidence to the optimization claim. Functional completion does not prove fewer allocations, lower memory, reduced network traffic, or lower latency; measure before and after with the relevant profiler or metric.
- For CSV exports, batch database reads and stream rows instead of materializing the complete relation and output buffer. Verify filters and pagination are applied before loading; if some report types bypass pagination, establish product-approved date, row, and filter bounds from workload evidence.
- Avoid mocks that erase the boundary under review. Preserve error type, transaction timing, concurrency, and response shape where they are the contract.
- Do not use `Faker.unique` when generating random values in factories; use global sequences instead, because its state leaks across tests and produces flaky failures.
- Middleware order is asserted in specs, and the Error handling and job sections above own the rules.
- Assert the property a test exists to prove; a case that passes for an incidental reason is not coverage. A spec that hardcodes the expected result for `page=0` passes only because `page=0` returns the same rows as `page=1`, so it never asserts the equivalence it protects.
- Treat moving a `let!` or `subject` between spec groups as a behavior change, because it changes which examples receive the side effect; only a plain `let` is safe to relocate. A `let!` hoisted into a parent group gives its side effect to sibling contexts that never relied on it.

## Latency, scaling, and infrastructure

- In HR Web request paths, offload work expected to exceed 500 ms. Treat this as a context-specific SLA, not an organisation-wide correctness threshold; verify the target service's SLO.
- Bound external work and avoid inline retry amplification, counting queue wait, pool checkout, serialization, and downstream work in the latency budget.
- Treat `OpenStruct` as a hot-path performance heuristic, and do not flag isolated tests, tools, or cold administrative paths without workload evidence. Benchmarks show `OpenStruct` with `Rails.cache` is about 3.4x slower and uses about 11.9x more memory in Ruby 3.0 than in 2.7, and YJIT cannot optimize its dynamic method lookup. Replace it with `Hash` or `Struct` on performance-critical paths and enable `Style/OpenStructUse`.
- In Rails 7.1, `connection.active?` alone is not proof that checkout and query use are healthy; health checks should exercise the behavior they claim to protect without causing unsafe load.
- Require measurable evidence for HPA, replica, worker concurrency, queue, web-server, timeout, and resource-limit changes: current utilization, traffic shape, p95/p99, saturation, OOM history, target, and rollback. Verify that multiple scaling signals will not conflict or oscillate, and model downstream capacity before increasing producers or replicas. Estimate production memory, CPU, connections, storage, and cost for infrastructure changes, including large-tenant and incident recovery behavior.
- Kubernetes resource changes require review from the platform owner in addition to application review, and raising limits must not replace fixing a demonstrated allocation or query defect.

## Caching and shared state

- For Redis clients, distinguish connect, pool, read, and write timeouts, and verify pool sizing and behavior when Redis is slow rather than unavailable. A timeout below about 5 seconds under many connections raises `Redis::CannotConnectError` even when Redis is healthy, because Redis is single-threaded and response time grows with connected clients; use the default 5 seconds or set per-action timeouts explicitly.
- One unbounded hot path degrades the whole pod: memory and CPU accumulation from a high-volume unbounded query makes unrelated endpoints look like independent defects. Diagnose resource accumulation at its source.
- Read-only mailer queries are a primary-load source during bulk sends; route them to replicas when the mailer does not decide or write from the read.
- PII arg scrubbing (`log_arguments = false` or omitted args) makes a worker invisible to args-signature duplicate detection: the same log field that identifies duplicate executions is destroyed by scrubbing. Balance PII protection against duplicate-detection observability.
- Log lookup attributes are a finite per-service budget: adding a new searchable attribute displaces an existing one and silently breaks operational search.
- Rails MemoryStore: every cache hit takes an exclusive write lock, a serialized write disguised as a read, so on a hot path it serializes all readers. A `Concurrent::Map` replacement must make the size guard atomic, because check-then-act overshoots, and must preserve per-caller copy semantics.
- Cache keys must include every dimension the data could be scoped to; a key that omits a scoping dimension returns silently wrong answers once the data becomes multi-scoped.
- A change that silently bypasses an established caching layer can exhaust database burst IOPS and degrade the whole application; review cache-bypass changes and hot-path cache additions for load and IOPS impact.
- Shallow `.freeze` on objects cached in a process-wide store leaves nested mutable state shared across threads and requests, so any later in-place mutation corrupts every consumer. Deep-freeze or copy per caller.
- Per-process caches in a horizontally scaled fleet have near-zero hit probability under load: quantify replica count before approving, because with many replicas holding different caches the hit rate collapses exactly when the cache is needed most.
- Long gRPC side effects inside a database transaction hold connection-pool slots and can exhaust the pool on upstream timeout; the failure is connection starvation, not only uncommitted-state visibility.

## Metrics, logging, and time

- Verify traffic assumptions using current metrics rather than historical anecdotes, and document the time window, environment, and revision behind the evidence.
- Preserve observability-field semantics: in current Sidekiq logging, JID locates one job while args signature plus status identifies duplicate executions. Review field removal against real search and alert use cases. Treat noisy logs and warnings as multi-sink load. Check log quota, error tracking, metrics, and alert fan-out so a fix does not silence only one symptom.
- Set request- and job-scoped `CurrentAttributes` once at the outermost execution frame and reset them afterward; nested setters silently overwrite identity or correlation context.
- Convert to the target timezone before calling `to_date`, and never mix `Time.now` and `Time.current` in the same worker. `7.days.ago.utc.to_date` in a UTC+7 application at 00:30 in that zone resolves to 17:30 UTC the previous day, so reconciliation and reminder windows silently miss or double-count a day; `Time.now` in system timezone versus `Time.current` in application timezone makes scheduled jobs fire at the wrong wall time; and DST transitions make `Time.zone.local` of a nonexistent time raise. A comment claiming "UTC dates — safe regardless of server timezone" is not evidence.
- Workers that make decisions or write based on reads must read from the primary. A worker that reads "documents waiting for recipient" from a replica and enqueues reminders misses recently committed writes under lag, and nothing re-checks. The replica read is a one-line helper call invisible in the diff, acceptable for reporting and dangerous for decision-making workers.
- ActiveJob logs job arguments before `around_perform` callbacks run, so arg-scrubbing concerns must also set `log_arguments = false`. The "Performing Job ... with arguments:" line fires through `perform_start.active_job` before around_perform, so a ParameterFilter concern that scrubs inside around_perform leaves PII in log aggregation.
- Do not override Sidekiq class methods (`perform_async`, `perform_in`, `perform_at`) and avoid the `.delay` and `.delay_for` mailer extensions; both change the serialization contract for every caller. Overriding enqueue methods with `super(*args, **options)` forwards kwargs as a hash arg, changing the payload shape, and `Mailer.delay_for(...)` YAML-serializes class, method, and args, so a mailer signature change silently breaks queued jobs.

## Release sequencing, static rules, and operational routing

- When rewriting or adding a static rule, justify it by precision and non-overlap with the rules the repository already enables, not by the name of the smell it claims to catch. A rule that flags every integer, or re-reports a result already parked in `.rubocop_todo.yml`, turns the findings-fixed rate into noise.
- Give every new cop an `Include:` matching the file set its model of the code holds for, and copy the `Exclude:` set, including the `Excludes` list, from the existing cop covering the same smell. Without `Include:`, a cop added to `config/default.yml` runs on every `.rb` file and reports on `spec_helper`, `rails_helper`, and `spec/support`, where its assumptions do not hold.
- Land every lint suppression and temporary severity setting with a tracked ticket and a removal condition, and read the pipeline's actual fail level before claiming the setting is non-blocking: with `rubocop --fail-level=warning` on changed files, a `Severity: warning` setting fails the build for every change touching those files.
- Treat a shared cache TTL reduction as a load-shape change: step down in roughly 25% increments and observe one step before the next, and confirm invalidation handlers tolerate a missing key. TTL length sets how many mass-expiry waves fall inside a business day, so halving it doubles the waves and their simultaneity.
- Ship a user-visible behavior change separately from the performance fix that motivated it, and do not stack a second risky change before the first has observation data.
- A change to a `lib/tasks/**/*.rake` task that enqueues billable or compliance work is a runtime release, not a refactor. A task that decides its enqueue set on `today.day == 1` duplicates a schedule `application-infrastructure` already owns, so the task fires daily while the guard decides the month, and the two drift with nothing failing. Name the enqueue set, the schedule's real owner, and the monitoring or count evidence; a task change carrying none of the three is an evidence gap rather than a code defect. Suppress for a pure extraction that leaves the enqueue set identical.

## Provisioning, hotfixes, and mirrored configuration

- Compute a plan once, derive every downstream size from that same plan, and raise a typed error when two inputs resolve to the same destination instead of letting the last writer win. Re-deriving a size lets the artifact drift from what was provisioned, and a mapping that overwrites an owner when two services share a port produces a wrong but quiet deployment; letting a broader handler swallow the ambiguity error restores the silence.
- Require exactly one match when a resolver shortens or falls back along a prefix of the key, and reject multiple matches instead of accepting the first: otherwise the winner is whichever sibling is listed first, and the plan is a guess that looks like a resolution.
- Make every initialization step part of the replacement path, not just first-time provisioning: a replaced resource comes up alive but empty, and no error surfaces until someone queries missing data.
- A hotfix waits for the same CI and staging evidence as a normal change; urgency is not a merge-gate exemption. Approving on urgency merges code whose failing specs or unrun end-to-end tests have not reported, and the revert lands on top of a production incident.
- Route an error to the sink its environment justifies: never let a development-only configuration page the shared error tracker, and give a recurring production cleanup path an alert instead of a silent rescue. A development config that reports every Kafka failure floods the shared tracker and buries the production errors alerting exists to surface, while a cleanup task whose rescue lets failures accumulate goes unnoticed until the store has degraded.
- When a security- or config-relevant list is mirrored in another file or repository, put the cross-reference comment in the file the next author will edit, naming the mirror. Two owners of one list drift silently: a new filtered parameter never reaches the collector's redaction config, and a new environment key never reaches the spec that enumerates the key set.
