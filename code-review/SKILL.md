---
name: code-review
description: "Use when reviewing a pull request to standard. Runs in Claude Code with a Haiku reviewer delegated for each domain, in parallel with a principles pass."
version: 1.17.1
license: MIT
---

# Pull request review

## Overview

One review pass, run to a fixed standard: pin the target, classify the change, apply the domain guidance that matches it, run a principles pass and a Haiku reviewer for each domain in parallel, verify every claim before it enters the report, write the findings in a fixed shape, and post only what the operator approves.

This file is the front door. It carries the contract, the step order, and the routing. Each step names the reference that holds its rules; read that reference when the step runs, not from memory, and not all at once.

## Reference routing

| Step | Subject | Read |
|------|---------|------|
| 0 | Establish the target, fetch, diff, re-review delta | `references/review-setup.md` |
| 1 | Classify frontend, backend, or mixed | this file |
| 2 | Apply the domain guidance for the change | `references/ruby-and-rails-review.md` (router to `references/ruby-and-rails/`), `references/leave-domain-review.md`, `references/reports-domain-review.md`, `references/frontend-shared-review.md`, `references/frontend-review.md`, `references/mobile-review.md` |
| 3 | Run the principles pass and the domain pass in parallel | this file, `references/domain-delegation.md` |
| 4 | Verify every claim, grade it, then synthesize | `references/rule-verification.md`, `references/test-and-lint-evidence.md`, `references/review-rubric.md`, and for a Ruby change `references/rails-change-traps.md` |
| 5 | Write in Google developer documentation style | `references/google-style.md` |
| 6 | Plain-language edit, finding record, fix versus push back | `references/output-and-drafting.md` |
| Post | One review, event matched to verdict, anchors, write verification | `references/github-review-posting.md` |
| Maintain | Change a rule, add a reference, check vocabulary | `references/maintaining-this-skill.md` |

Load a reference once per review, at the step that needs it. Loading every reference up front spends attention that should go on reading the diff.

## Review contract

- Pin the repository, the base branch, the merge base, the exact head commit, the changed-file set, and the repository's current contribution guidance before reading the diff. Every later claim names that head.
- A review writes nothing to the pull request or to the checkout until the operator authorizes it. Findings stay in the review file until then.
- Ground each finding in current code: the path, the expected contract, the observed divergence, and the evidence. Quote the source line beside the anchor.
- **Anything a CI job decides is out of scope.** Do not run the test suite, a linter, or a type-checker, and do not raise a finding that a naming, formatting, cop, or type rule would produce. Read the pipeline's own result when a claim depends on it, and report only what CI cannot decide.
- Keep questions, assumptions, and verification gaps in their own section, never mixed into the findings.
- Open the review file with a step ledger: Steps 0 to 6 and the posting step, each marked `run`, `partial`, `skipped`, or `read` with the reason, plus the head commit it ran against. A step that disappears without a line in the ledger is exactly the defect the ledger exists to catch.
- Call a claim verified only when the check ran against the reviewed head and you can name the command or the file you read.

## Step 0: establish the target

Read `references/review-setup.md`. It carries the pinning commands, the base-resolution rule, the API fallback when the head cannot be read from a checkout, the files to leave out of the reading set, and the re-review delta procedure.

This step produces one recorded tuple: repository, base, merge base, head commit, changed-file set, and whether the pass is a full review or a delta review.

## Step 1: classify the change

Classify from the changed-file set, not from the title:

- **Frontend:** the `frontend-core` or `eh-mobile-pro` repositories; React, TypeScript, JSX, React Native, Hero Design, components, navigation, CSS, forms, i18n, mobile lifecycle.
- **Backend:** Ruby and Rails repositories and services; migrations, models, Sidekiq, Kafka, gRPC, GraphQL and REST endpoints, Pundit policies, background jobs.
- **Mixed:** split the file set and apply each guidance set to the files it owns.
- **Tie-break:** classify by where the behaviour is enforced. Server-enforced behaviour is backend, UI-only behaviour is frontend. If it is still ambiguous, classify by dominant changed-line count and state the assumption in the output.

## Step 2: apply the domain guidance

The domain rule sets ship with this skill. Read the one that matches the classification, and within it the surfaces the change touches. A rule set that ships as a router names its subject files; the router's table is the rule for choosing among them, so the set is read for the change rather than for the classification alone.

- **Backend, Ruby and Rails:** `references/ruby-and-rails-review.md` is a router, not a rule set. Read `references/ruby-and-rails/essential-checks.md` on every Ruby change, then the subject files its table selects for the changed code: data and migrations, jobs and queues, messaging and contracts, security and authorization, quality and operations, error handling, typed data objects, architecture and proposals. Cap the set at three subjects plus the essential checks, and record which files were read in the ledger.
- **Leave-domain backend change:** also read `references/leave-domain-review.md`, and start with the one surface section the change is about, plus the single leave-wiki page that owns it at a pinned commit; a balance read is not a category change. Read a second section only when the change crosses that seam, and say which two in the ledger. A change that crosses Leave–Workflow or Leave–Payroll also reads the scenario coverage section, which names the matrix cells that have to be tested.
- **Reports-domain change:** a change to `reports-service`, to the report code of `employment-hero` (`DashboardReport`, `StandardReport`, `ReportWidget`, `report_widgets/`, `reports_registration/`, `ReportsData` sync), to custom reports (BYOR: `CustomReport`, `CustomReports::*`, `custom_reports/`, `custom_report_files`), or to the `frontend-core` reports module and its `ReportCanvas/` builder also reads `references/reports-domain-review.md`. A BYOR change reads the `Custom reports (BYOR)` section's subsection for each layer it touches and checks that the counterpart change on the other layers exists. Read its orientation map, then the sections for the surfaces the change touches; a change to a `ReportsData` decorator or publisher also reads the reports-service ingest section, because the defect usually lands on the other side of the topic. Name the sections read in the ledger.
- **Frontend, web or React Native:** start with `references/frontend-shared-review.md`, which carries the principles both surfaces share: data and state, error and loading semantics, identity and tenant scoping, feature flags, types, accessibility, conventions, test quality, test assertions, and locale files.
- **Frontend web:** then `references/frontend-review.md` for components, Hero Design, forms and tables, i18n, routing, web tests, and the web test runner.
- **React Native:** then `references/mobile-review.md` for navigation and lifecycle, offline and sync, and native platform behaviour.
- **Frontend mechanics sweep:** after the domain rules, read the changed selectors, hooks, spec files and message ids a second time and answer four questions in the ledger, each with a finding or an explicit none: every selector or derived value (`createSelector`, output identity, an existing selector over the same inputs); every hook and dependency array (a ref in the array, a ref where state belongs, timer ownership and cleanup); every spec file (one scenario per `it`, table form, the real component over a mock, the wrapper the file already has); every message id (`t` macro, placeholder present); every type added or widened (a `Record`, `any`, or `as` over a shape the module knows, a type declared in a component that state imports). A pass that reaches the end without answering these has not read the mechanics.
- **Mixed change:** read both, each scoped to the files it owns.
- **A repository that carries its own review guidance wins** where the two disagree, and the review says which one decided.
- The base branch: for `employment-hero` the base is `development`, unless the pull request is a layer of a stack, where the base is the branch it targets; `references/review-setup.md` carries the layer rules. The review always states the base and the merge base.

Collect findings with `path:line`, expected versus observed behaviour, consequence, and evidence. Keep attribution separate: repository contract, general engineering rule, observed author preference.

A section that restates one of the organisation's published rules carries that rule's identifier in its heading. Those rules outrank this skill where they conflict, and a review that departs from one says so.

## Step 3: run the principles pass and the domain pass in parallel

Two passes answer different questions, so dispatch them together and let them run concurrently while you take your own reading of the diff. Write your own findings while they run, and read theirs only after yours are written; the hardest defect to catch is the one your own reading already explained away.

Read `references/domain-delegation.md` before the first brief. It carries the pass table, the brief, the return shape, the acceptance rule, and the ledger line.

- **One batch.** The principles pass and every domain pass go out together, so the wait is the slowest pass rather than the sum of them. Dispatched one after another they cost the total, which is the delay this shape exists to remove.
- **One domain pass per domain, plus exactly one principles pass.** A mixed change gets one Haiku reviewer for each domain its files touch, each told which files it owns: Ruby and Rails, leave domain, reports domain, shared frontend, web, React Native. The principles pass is scoped to the whole changed-file set and is never split by domain.
- **The principles pass carries no domain rule set.** It is briefed with the primary coding principles: correctness, ownership of state, boundaries and contract shape, error handling, reachability of the value under test, test signal, duplication, and dead code. Its value is reading the same lines without the domain's assumptions, and a principles pass handed the domain reference is a second domain pass.
- **No emphasis split.** Both passes report both classes in one brief. Correctness is bugs, breakages, security, authorization, feature-flag leaks, data loss, and contract changes; maintainability is responsibilities, duplication, error handling, test signal, and dead code. Sending one pass per emphasis re-reads a single file twice and returns two lists whose overlap you then reconcile by hand.
- **A tool-call budget with a stop-and-write rule.** Size the budget above the change rather than below it: a starved pass returns a partial list, and an absent budget returns a pass that explores until its context fills. The brief states the number and the call at which the pass stops reading and writes what it has.
- **A reading boundary.** Name the changed files at the pinned commit, allow an exact-path read for a caller, sibling, or spec that a finding needs, and close the boundary against repository-wide recursive search, network fetches, package installs, and dependency source trees. Read no gem's source except `eh_protobuf` and `eh-keypay`, which are the organisation's own and are read at the version the lockfile pins; a claim that needs any other library is returned as unread with the library and version named.
- **The machine-checkable exclusion, as its own sentence.** A pass does not run the test suite, a linter, or a type-checker, and does not report naming, formatting, cop, or type findings. Anything a CI job decides is left to CI, and its result is read as evidence rather than reproduced.
- **Model.** Every delegated pass runs `claude-haiku-5-5` at high reasoning effort. The id is fixed with no date suffix and no separate alias, so there is nothing to pin forward and no alias to drift; the effort is the part that is easy to lose, because a Haiku pass left at the default effort reads shallowly and returns the findings the parent already explained away. Set it explicitly where the surface exposes an effort control, and record in the ledger the model and effort that actually ran.
- **Read-only.** A delegate gets Read, Grep, and Glob, and returns candidate findings only: no writes, no posts, no severity, no verdict.
- **Acceptance.** A returned finding is a hypothesis. It enters the report only after you reproduce its quoted line at the head commit, and a finding that does not survive is dropped with its reason in the ledger.
- A change that is documentation, locale strings, or configuration with no executable path runs the domain pass only, and the ledger records the skipped principles pass and its reason.

## Step 4: verify, then synthesize

Verify each claim before it enters the report, then merge the verified findings.

- `references/rule-verification.md` decides whether a claim is true at the reviewed head: anchors, counts, absence claims, diff markers, base-revision comparisons, equivalence and cycle claims, severity relabelling, and stale bodies and threads.
- `references/test-and-lint-evidence.md` decides what counts as test and lint evidence: check runs and annotations, an absent run, simulation versus gate, the review gate config, predictive test selection, spec response helpers, and vacuous assertions.
- `references/review-rubric.md` holds the decision procedure: the changed-contract questions, the nine-field record that validates a candidate finding, the severity table, the decision posture, and the evidence authority rules. Grade every finding through it before it enters the report; the severity table decides the level, and a typical-severity band stated in a domain reference is a starting point that the table resolves.
- `references/rails-change-traps.md` holds the Ruby, Grape, and Active Record mechanisms that settle a claim the diff cannot: stored versus written form, sparse writers, removed keywords, forwarded parameters, replaced-route predicates, and framework probes. Read it on any Ruby change.
- Merge the two passes: deduplicate overlapping findings and weight one raised twice more heavily, by you or by a delegate. Resolve a disagreement between your reading and a delegate's with current code and tests, and state when you did.
- Order findings by severity and confidence, findings first. When nothing survives, say so explicitly and list the material evidence gaps.

## Step 5: write in Google developer documentation style

Read `references/google-style.md` in this run, before any comment is drafted, and apply it to every synthesized comment. Three rules carry most of the value: condition before instruction; second person, active voice, present tense; every performance, cost, or security claim states its source. Rules applied from memory lose the specifics (condition before instruction, short sentences, "only" placed before what it limits). Record the read in the step ledger.

## Step 6: plain-language edit and finding record

Read `references/output-and-drafting.md`. It carries the plain-language edit list, the finding record, the ordering and attribution rules, the durable review file, the confirm-before-posting split, the explain-a-finding rule, and the fix-versus-push-back procedure.

Put the edit's receipt in the step ledger. When the edit is skipped, say so in the delivery message rather than marking the step complete.

## Posting

Read `references/github-review-posting.md` before any write. It carries the one-review payload, the event-to-verdict rule, the hunk-anchor check, write verification, the approval form, and the head-moved re-verification.

Nothing is posted until the operator approves the post-or-defer split.

## Maintaining this skill

Read `references/maintaining-this-skill.md` before changing anything in this skill. It carries the file-to-subject map, the bar a new rule has to clear, the vocabulary these files must not carry, and the checks a change has to pass.

The canonical copy lives in the skill hub repository under `skills/code-review/`, and every installed copy is a copy of that directory. Edit the hub copy, reinstall the entry, and prove parity with a directory diff.

## Guardrails

1. When the title or repository name suggests a different domain than the changed files, classify from the files and state which signal decided.
2. When a change mixes domains, split the file set and apply each guidance set to its own files.
3. A delegate never replaces your own pass. Your findings are written before its brief is sent, and a returned finding is a hypothesis until it survives the record in `references/review-rubric.md`. A pass whose delegate failed, or ran on a substituted model, says so in the ledger instead of claiming the step complete.
4. When the two passes disagree, resolve it with judgement on current code and tests, and say that you did.
5. The style read and the plain-language edit are the final delivery steps on every review, and each gets a line in the ledger: `read` plus the file for the style reference, `run` or `skipped` for the edit. A delivery message that omits both lines is incomplete.
6. Before an authorized write, re-fetch the head, the review comments, and the reviews. A reviewer or bot can post threads mid-review, so a comment list read at Step 0 is stale by the time you post. Classify the threads you find as fix, reply, stale, or duplicate; reply on the existing thread instead of opening a second one for the same finding, and disclose the duplicate if you already posted one.
7. When a prior review, a saved review record, or a moved head indicates a re-review, run Step 0 first and scope every pass to the delta. Do not re-review the full pull request from scratch.
8. Read a step's reference before running that step. A pass that leans on this front door alone is missing the rule sets that catch the expensive defects.
