# Rails, Grape, and ActiveRecord traps

Step 4 rules for Ruby changes, where the mechanism decides a claim that the diff cannot. Read this file when the changed files are Ruby, or when the change touches a Rails route, a Grape endpoint, a serializer, or an ActiveRecord write.

## A stored value is not the form the schema implies

Compare a stored value against the form the writer produced, not the form the schema suggests. `record.attributes[...]` returns the raw column value, so an enum reads as its integer and a date as a `Date`. A port that merges stored attributes into a payload and compares that integer to the enum's string constant never matches, and the guard stops guarding on exactly the sparse path the port introduced. Read the column definition and the enum mapping beside the comparison, and check whether any spec sends that key alone.

## A sparse writer must carry every sibling key its callee reads

When a full-form writer becomes a sparse one, a key the change derives from stored state must carry every sibling key the layer it calls reads at the same time. A derived pay-setup option written without the pay-category id the validator checks beside it turns a valid save into a 422, and a class comment claiming the value is checked as stored covers the value, not the ids it requires.

## A removed or renamed keyword breaks a caller the diff never touched

When a diff removes or renames an argument or a keyword, sweep every caller and every spec at head for the old name:

```
git grep -n 'HelperName' HEAD_SHA -- '*.rb'
```

A caller left passing it raises `ArgumentError: unknown keyword` at its first call, and it is usually a spec in a file the diff never touched, so a run scoped to the changed files stays green. Run this sweep during synthesis rather than trusting a changed-file-scoped test claim.

## A forwarded parameter is a behaviour change on every existing caller

A change that only forwards a parameter the receiver already accepts is an unflagged behaviour change on every caller that already passes it. Prove two things before accepting it:

1. That the receiver reads the value at head: the endpoint's params block declares it and the service call below consumes it (`optional :leave_request_id` with `excluded_leave_request_ids: [params[:leave_request_id]].compact`). A forwarded parameter the receiver ignores changes nothing while reading as a fix.
2. Which callers already supply it. The change lands on all of them at once, including screens the ticket never names, and a body that describes only the newly wired caller is a scope gap. Each existing caller needs its own regression assertion.

A kill switch does not cover this class: the fix ships unflagged.

## A replaced route is verified against the route it replaces

For a port, consolidation, or replacement of an existing route, verify the authorization claim against the predicate of the route the change REPLACES, not only against the new family's sibling endpoints. Sibling parity hides the difference that matters: a replacement that drops a feature-flag guard, or keeps only one branch of the old predicate (a `manage? || manage_via_css_*` pair collapsed to the CSS arm), matches every sibling while still widening or narrowing access. Read the old route's gate and compare it term by term, including the flag terms.

## `create_table id:` is a column type, and only the adapter decides the SQL

A `create_table ..., id: :bigint` line reads like "use a bigint id". The `id:` value becomes the primary
key's **type**, not a switch, and what that type generates is the adapter's decision:

- `TableDefinition#set_primary_key` passes `id` to `primary_key(pk, id, **options)`, which is
  `column(name, type, primary_key: true)`.
- Creating that column routes the type through the adapter's `integer_like_primary_key_type` hook
  (`schema_definitions.rb` calls it for a primary key column). The abstract definition returns the type
  unchanged, so an abstract-only reading makes `:bigint` look like a bare `bigint` with no sequence.
- PostgreSQL overrides the hook (`postgresql/schema_definitions.rb`): `:bigint` becomes `:bigserial`, and
  every other integer-like type gets `:serial`. So `id: :bigint` generates
  `"id" bigserial NOT NULL PRIMARY KEY` and auto-increments. The abstract-only reading is wrong here, and
  wrong in the direction that invents a High finding about a table that cannot be inserted into.

Settle a generated-DDL claim from the repository's own evidence, never from the abstract definition: the
`db/schema.rb` line a migration produced, an existing table created the same way, or a spec that creates and
inspects the table. The mechanism above is what makes those observations decidable, and the emitted
statement is what the finding quotes. Where only the gem's own source could settle it, that source is not
read: return the claim as unread, with the gem and its version named.

Two consequences survive whatever the type turns out to be:

- A migration edited after it merged only changes databases that have not run it: `if_not_exists: true`
  makes the statement a no-op wherever the table exists, so environments diverge while the committed
  schema file describes neither version. An unrelated migration edit inside a feature pull request is
  worth raising as a revert-and-own-change request in the review body rather than as a line defect.
- A repository check on the migration DSL fires when someone migrates, not in CI. This repository's
  `StrongMigrations.add_check` stops any `create_table` whose options string carries `=>:serial`, and it
  inspects the call rather than the database, so `if_not_exists: true` does not avoid it. Jobs that load
  the schema (`db:schema:load`) never execute a migration, so one that aborts every deploy stays green in
  CI and surfaces only when a workspace migrates. When a change carries an unrelated migration edit, ask
  what made the author run migrations at all — that answer is usually the real blocker to report.

## Two time-parsing idioms agree only for strings that carry an offset

A port that swaps `Time.parse(raw).in_time_zone` for `Time.zone.parse(raw)` changes behaviour for naive input only. The first reads the wall clock in the process zone and converts; the second reads it in `Time.zone` directly. Every string with an explicit offset produces the same `rfc3339` from both, so the diff alone cannot decide whether a "matches the internal serializer" claim holds.

Settle it in three steps, in this order:

1. **Read the writer, not the reader.** Find the code that stores the field. An assignment of a `TimeWithZone` (a parse result, `Time.current`) serialises with an offset and cannot diverge; a formatted string or an upstream API value can.
2. **Check whether the repository already parses that same field one way.** A sibling parse of the same column names the reading its producer intends, and often settles the claim without a probe.
3. **Probe the equivalence** over the zones the change claims to serve, with the repository's own Ruby (`.ruby-version`) and the `activesupport` from the lockfile — the system Ruby usually has no gems:

```
ACTIVESUPPORT_VERSION=<from Gemfile.lock> rbenv exec ruby \
  <skill dir>/scripts/time_parse_equivalence.rb "<raw1>" "<raw2>"
```

Report a divergence confined to a form the writer never stores as a question, not a finding. The script states the verdict per zone and closes with that instruction.

## A status code or coercion claim needs a probe

A framework claim about a status code or a coercion is settled by a probe against the pinned gem version, never by reading the framework's validation source. Grape's validator source reads as if an optional param carrying an empty value skips validation, so the coerced branch looks unreachable and a null input looks like the service's 422. A `Rack::MockRequest` app built from the same params block shows the `coerce_with` lambda running for both `null` and `""`, with the framework answering 400 before the endpoint executes.

- Reproduce the params block in isolation.
- Echo the endpoint's own view (`declared(params, include_missing: false)`) so you see exactly what it receives.
- Take both gem versions from the lockfile.
- Treat the probe run as the evidence class. A claim that a service-level branch is what the HTTP layer exercises is only true once the probe agrees.

## A member-state gate reads wider than it is until each branch is reduced

A predicate stacked from state options looks like an over-grant beside the single check it replaced, and the abstract reading invents a High. Reduce every branch to its own preconditions before reporting one. Given:

```
member_state_access?(allow_preboarding: true, allow_postboarding: true)
```

- `allow_preboarding` returns true only when `preboarding_member?`, and `Member#preboarding?` returns false unless `active_member?` (`active && accepted`), so preboarding is a subset of active rather than a state beside it.
- `allow_postboarding` returns true when the policy's `active_member?` holds and the member is not preboarding, and that policy helper reads the `active` column.

The union of the two branches is the `active` column alone, which is what the `AccountPolicy#active_admin_or_owner?` it replaced evaluated. State the reduction in the review file and withdraw the finding; keep it only when a branch's own precondition admits a state the old check refused.

The general form: settle a multi-branch state predicate by reading each branch's guard in its defining concern (`app/models/concerns/member/preboarding_helper.rb` for this one), never by reading the option names. Option names describe intent; the branch bodies decide reach.

## Where framework behaviour is settled

No gem's source is read, apart from `eh_protobuf` and `eh-keypay` at the version the lockfile pins; the boundary is in `references/review-setup.md`. A claim that needs any other library's source is returned as unread, with the library and version named, rather than promoted to a finding.

The repository settles most of these claims itself, and that evidence outranks a reading of the library:

- An in-repo call site of the same framework API. A serializer that already carries `attribute :name, if: :predicate?`, or a policy that already calls the helper, establishes that the API is supported and how it is invoked at this revision.
- A generated artifact the framework wrote. The `db/schema.rb` line a migration produced, or an existing table built the same way, is the framework's own output for this application.
- A spec that can only pass if the claimed semantics hold. One route returning 200 while its sibling returns 403 proves per-route dispatch; a shipped endpoint with the same declaration shape proves the declaration survives.

Say which of the three you read, because a precedent proves the API exists and is invoked this way, a generated line proves the output shape, and a spec proves the behaviour at that revision. When the bundle is not installed in the checkout, the in-repo call site is the cheaper proof, and it is the only one available: library source is out of bounds either way.
