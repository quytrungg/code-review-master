# Test and lint evidence

Step 4 rules for the surface that decides most "it passes" claims. Read this file when Step 4 runs.

## Test evidence comes from the head commit's checks

Verify a claim about test evidence against the head commit's checks, never against the pull request body or a bot's gate comment:

```
gh api repos/OWNER/REPO/commits/HEAD_SHA/check-runs
gh api repos/OWNER/REPO/check-runs/RUN_ID/annotations
```

The annotations call returns one annotation per failing example, carrying its spec path, line, title, and the raised error. A body that claims "N examples, 0 failures" is pinned to the revision it was written against, and a red check run on the head is both a merge blocker and the cheapest proof that the claimed green run did not happen on this revision.

**At a re-review the body's counts are the evidence most likely to be stale, and they are checkable.** A fix round edits the examples and rarely edits the body, so a quoted "N examples" is left describing the previous head by construction. Count the new head's **runtime** examples from the block, not its declarations: a loop around four examples (`%w[AU NZ].each`) runs eight, and an example added inside one context moves the total by one. Compare that number with the figure the body quotes; when they differ, report the evidence as measured at an earlier revision and ask for a re-run or a named revision, rather than inheriting the stale figure as though it described the head. The same arithmetic reconciles a deliberate-red run, whose failures must decompose into the examples that depend on the mutated value.

## An absent run is an evidence gap, not a green

When `check-runs` carries no run for the suite the body names, list what did run for that head and read the repository's required-workflow list:

```
gh api 'repos/OWNER/REPO/actions/runs?head_sha=HEAD_SHA'
```

- A required test job can be a workflow run rather than a check run, so an empty `check-runs` list does not mean CI never ran. Query both, and take the required set from the repository's own configuration or bot comment.
- When a required job has no run on the head, report the suite as unexecuted on that revision. A green deploy, lint, or compliance job does not stand in for it.
- Read the workflow's `on:` trigger before calling the absence a defect of the pull request. A suite declared `workflow_call` only, or one fired by a bot comment, never starts on a pull-request event, so its absence is the repository's normal state and belongs in the evidence gaps rather than the findings. Name the trigger you read.
- A run from a developer machine, or an interactive shell, is a simulation against that revision rather than a gate. Say which of the two you read: a gate run, or a simulation.
- Never present a run from a checkout that does not contain the head as evidence about the change. `references/review-setup.md` carries the revision check.
- **A pipeline with no test job at all is the same gap, and one read settles it for the whole head.** Some repositories run only compliance and bot checks — codeownership, a Danger pass, a secret scan, a vendor guard — and carry no type-check and no test job. `gh pr checks` listing only those is not a partially green pipeline: nothing about the change is machine-verified, so the body's own counts are self-reported and the evidence section says exactly that rather than implying a suite ran. `frontend-core` is this shape; read its check list before writing a frontend evidence section, and check the workflow trigger before calling a job missing rather than unstarted.

## The default lint command is not the review gate

Where a repository keeps a review config beside its default one (`eslint-code-review.config.js` next to `eslint.config.js`, run over the diff), `yarn lint` passing proves nothing about the gate: it loads the default config, and a clean run there can sit beside a finding on the same diff.

- Name the gate config and read its result from CI. Its `files` globs are root-relative, so an app-relative invocation matches none of them, which is a reason a local run misleads rather than a reason to run one here.
- Read the result into the step ledger rather than describing it as clean.
- When a gate error looks pre-existing, check the same line at base and head: an identical construct shifted by an inserted import is pre-existing, and a rule newly triggered by an added line is not.

## A predictive run is not the full suite

When the only test job on the head is a Crystalball-style selection, read which files it selected before quoting its result:

```
gh api repos/OWNER/REPO/actions/jobs/JOB_ID/logs --allow-escape-sequences > job.log
```

Then search the log for the changed spec paths and the `N examples, 0 failures` line. Without `--allow-escape-sequences`, `gh` answers `the response contains escape sequences` and the redirect writes a zero-byte file, which reads like a run that never happened. Quoting the selected paths turns "the full suite was skipped" from an unresolved gap into a stated evidence class.

**In `employment-hero`, the trigger decides whether any suite runs at all.** `build_pr.yml` is `workflow_dispatch` only and `unit_testing.yml` is `workflow_call` only, so a `pull_request`-event `check-runs` read on the head shows compliance, gitleaks, brakeman, jwt, PR Compliance and the bot-comment dispatcher, and nothing else. An absent suite there is the repository's normal state, not a finding; name the two triggers you read instead of reporting a missing test job. Marking the draft ready for review, or dispatching `build_pr`, starts the pipeline, which then runs `unit_local / crystalball_unit_test / run_predictive_unit_tests` over the predicted files and reports `unit_local / full_unit_test`, `unit_local / merge_crystalball_data` and `e2e_test` as `skipped` unless the Full Suite checkbox is used. The same head therefore carries two different evidence classes either side of the draft flip: predictive green covers the change's own specs when the Crystalball comment lists them, and it is never a full-suite green. Read the conclusions from `commits/<sha>/check-runs` after the flip rather than carrying forward the earlier gap.

## A test proves the mechanism only when it goes red without it

- A negative expectation on a Rails model class cannot fire through an association. `expect(Model).not_to receive(:where)` watches the class method while the code calls `Relation#where` on a `CollectionProxy`, which subclasses `Relation`, so the example passes whether or not the query ran. Count the table in `sql.active_record` instead.
- Stubbing a batch size to 1 makes a sliced query and an unsliced one return the same rows, so the example cannot distinguish them. `receive(...).once` proves invocation, not that the result was used.
- Name the observable that changes when the mechanism is removed before accepting the example's title.
- **Reconcile a claimed deliberate-red run arithmetically before quoting it.** A body that reports "the
  test was made to fail, then reverted" is a claim like any other, and its counts are checkable: the
  failures should equal the number of examples that depend on the mutated value — a guard asserting the
  constant, plus one example per cohort, context or case that compares against it. A count that matches no
  such decomposition is a run from another revision, or an earlier state of the block, and belongs in the
  evidence gaps rather than in the review. State in the review whether it reconciled.
- **An example that repeats an assertion already made in the same context adds a passing example, not
  coverage.** Typical shape: a title claiming the contract's two-sides distinction (a delta versus a total,
  `null` versus `0`), while the body only re-checks key presence and a figure asserted twice above it. It
  cannot fail unless an earlier example fails first, so it also hides the distinction it names. Name the
  title/body mismatch and ask for the assertion the title promises, or for the example to go.

## A stub proves its gate only when the matcher's arity matches the call

A spec helper that stubs `with(key)` does not match a production call that passes a context and an options hash, so the gate falls through to the real implementation and the example proves the opposite of what its title claims. Read the helper's `with(...)` matcher beside the call it is meant to intercept, and confirm the arguments match or that `any_args` covers them, before accepting any spec that claims to prove a flag, permission, or entitlement gate.

## A self-comparing example cannot prove a value

An example that compares the change against itself — masked output to unmasked output from the same serializer, one endpoint to a sibling that routes through the same class, a field to the value it was derived from — passes whenever both sides move together, including when both are nil. It proves the field is not dropped, and nothing about its value or format. To prove a value, assert it against a literal or an independently derived expected value.

Then prove a new public field is asserted somewhere at all. The new file's own examples often name a field in a title that the body never checks, so run a symbol-indexed grep over the whole spec tree rather than trusting the new examples:

```
git grep -n '\[:<field>\]' HEAD_SHA -- spec/
```

An empty result is a stated gap, not a coverage claim: the new contract has no concrete assertion, so a change to its format, or a nil, passes every example in the pull request. Report the example whose title claims the field it does not assert beside that gap, and check whether a parity example deliberately excludes the field before assuming the omission is an oversight.

## Read the spec's own response helper before calling an assertion vacuous

Repositories mix `JSON.parse` (string keys), `.with_indifferent_access` (string keys, indifferent reads) and `.deep_symbolize_keys` (symbol keys), and one file often defines its own `json_response` while the next uses the shared helper, so the same pull request can hold both forms. A `:key` lookup that returns nil in one file returns the value in another, and `item.keys.include?('x')` is meaningful only under the string-key forms. The helper decides the claim; the diff cannot.

Read the state the assertion mutates as well. A case that resets the other slice and expects the selector's value unchanged is a decoupling test that fails the moment the code reads that slice, which makes it the strongest case in the file rather than the weakest.

## A `let` or helper that issues the request hides the example's inputs

A fixture that performs the HTTP call or the query on first reference moves the example's state out of the example body: the reader sees an assertion and never the request, so which state was exercised is decided by hook order. A `before` later added above a flag toggle, a `let!` promoted into the parent, or a reordered nested context then changes what the example builds while its body still reads the same. Treat it as a finding when the example name or the surrounding comment claims a state: the file's other examples call the request helper explicitly inside the body, and that contrast is the correction to ask for. Assertions inside the same helper compound it, because the example cannot then choose the status it expects and a cohort that legitimately returns no rows cannot use it.

## A lint result is read, never reproduced

Lint is CI's to run, so this review raises no cop, naming, or formatting finding of its own. When the evidence carries one, quote the check's annotation and leave the cop's enabled state to the pipeline; do not copy the head's text out to lint it, and never switch a shared checkout's branch to obtain a run. A lint item that cannot be settled from the annotation stays an evidence gap.
