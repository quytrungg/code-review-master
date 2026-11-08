# Ruby and Rails review

This file is the entry point for a Ruby or Rails change and the rule for choosing its subject files. Read `essential-checks.md` on every Ruby change, then each subject file the changed code touches — and nothing else. The whole set is 120 KB; a review that loads all of it pays for eight subjects it never uses, on every later call.

## Choose from the change, not the title

Read `references/ruby-and-rails/essential-checks.md` every time. It carries the checks that apply whatever subsystem the change lives in, and it is small enough to always ride along.

| Read | When the change touches |
|------|-------------------------|
| `references/ruby-and-rails/data-and-migrations.md` | `db/migrate`, `db/schema.rb` or another generated schema file, a model's columns, associations, validations or scopes, a query path, an index, a replica or consistency choice, pagination, or a backfill |
| `references/ruby-and-rails/jobs-and-queues.md` | a worker, job, Sidekiq configuration, queue, retry or deduplication policy, outbox or inbox, scheduling, or work published from inside a transaction |
| `references/ruby-and-rails/messaging-and-contracts.md` | a Kafka topic, gRPC service, message payload, producer or consumer contract, broker naming, schema-registry entry, or a cross-service event |
| `references/ruby-and-rails/security-and-authorization.md` | a Pundit policy, permission, entitlement, feature flag, role check, tenant or member scope, secret, token, rate limit, or an externally reachable endpoint |
| `references/ruby-and-rails/quality-tests-and-operations.md` | a spec, factory, test helper, lint configuration, service or command object, dependency, configuration file, logging or monitoring, a `lib/tasks` rake task, a CI workflow file, or an operational rollout |
| `references/ruby-and-rails/error-handling.md` | a rescue, raise, boundary handler, error mapping, or a job that decides between technical failure and a domain outcome |
| `references/ruby-and-rails/typed-data-objects.md` | a new data carrier: a `Hash` argument, a multi-field return, a `Struct`, `Data`, or a class that exists to hold fields |
| `references/ruby-and-rails/architecture-and-proposals.md` | a design or proposal document, a new service or module, a cross-system design, an ownership or migration plan, or a decision that compares options |

## Rules for the choice

- Cap the set at three subject files plus `essential-checks.md`. A change that seems to need more is usually two changes; say so rather than loading everything.
- When a bullet names a subject that lives in another file, read that file before applying the bullet. The check and the rule it points at are one contract.
- Record the files read in the step ledger. A review that named a subject but never opened it is indistinguishable from one that read and cleared it.
- Where the domain is genuinely unclear, read `quality-tests-and-operations.md` with `essential-checks.md` and record the uncertainty in the ledger.
- The delegation step names the chosen files in the brief, so a delegated pass reads the same set as the parent. Where the parent cannot decide before dispatch, it names this file and the pass applies the table itself, recording which subjects it read.
