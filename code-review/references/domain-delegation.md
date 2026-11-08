# Delegating the two passes

This skill runs in Claude Code. The principles pass and the domain pass are delegated together in one batch, so they run concurrently with each other and with the parent's own reading.

A delegate is a recall net, not an authority. It finds candidates quickly and cheaply; every candidate still has to survive the nine-field record in `references/review-rubric.md` before it enters the report. A delegate never decides that a finding is real, and never writes the comment.

## Which passes to send

Send exactly one principles pass, scoped to the whole changed-file set. Send one domain pass for each domain the change touches, scoped to the files that domain owns, so no pass spends attention outside its own subject.

| Pass | The delegate reads | Its scope |
|------|--------------------|-----------|
| Principles | the principle list carried in its brief, plus `references/review-rubric.md` for the return record | the whole changed-file set |
| Ruby and Rails | `references/ruby-and-rails-review.md`, which routes to `references/ruby-and-rails/` | migrations, models, jobs, controllers, policies, services, serializers |
| Leave domain | `references/leave-domain-review.md` | any leave surface: balances, accrual, requests, categories, payroll sync, reporting |
| Reports domain | `references/reports-domain-review.md` | report access and tenant scoping, report lifecycle, widget data and filters, exports, custom reports (BYOR) across main app, reports-service and the canvas, `ReportsData` sync, reports-service catalog, query modules and engines, the frontend reports module |
| Shared frontend | `references/frontend-shared-review.md` | state, effects, identity and tenant scoping, flags, types, accessibility, tests |
| Web | `references/frontend-review.md` | React components, Hero Design, forms and tables, i18n, routing, web tests |
| React Native | `references/mobile-review.md` | navigation and lifecycle, offline and sync, native behaviour |

A web change reads the shared file before the web file, so its domain pass is told the same order. A change that touches both web and mobile needs both domain passes plus the shared one.

The principles pass is the one pass briefed with rules rather than a reference path, because its list is short and there is no corpus to paraphrase. Do not add a domain reference to it: a principles pass handed the domain rule set is a second domain pass, and the review then pays twice for one reading.

## The brief

Write each brief from this shape and keep it short enough to read in one pass.

```
You are the <principles | domain> pass reviewing <surface> at commit <sha>.
Read <reference path> and apply it.
Primary coding principles: <the list, principles pass only>
Base <base>. Merge base <merge base>.
Your files: <the changed files this pass owns>.
Budget: 60 tool calls. At call 50, stop reading and write your report.
Reading boundary: read only the files above at the pinned commit, plus an exact-path read
for a caller, sibling, or spec that a finding needs. No repository-wide recursive search,
no network fetch, no package install, no dependency source tree. Read no gem's source
except eh_protobuf and eh-keypay, at the version the lockfile pins; return any other
library claim as unread, naming the library and version.
Do not run the test suite, a linter, or a type-checker. Anything a CI job decides is out
of scope, and a naming, formatting, cop, or type finding is not a finding.
Return candidate findings only: path:line, expected behaviour, observed behaviour, the
consequence, the source line you read, and your confidence. Quote the source line beside
every finding. Do not write files, do not post, do not grade severity, do not state a
verdict. If the reference or a file you need cannot be read, name it and stop.
Close with: calls_used, stopped_because (done | budget), unread.
```

Six things the brief must not leave out:

- The head commit, never a branch name. A delegate that resolves `development` reviews a different tree from yours, and its findings cannot be reproduced at the pin.
- The reference path for a domain pass, not the rules. A delegate briefed with the rules paraphrases them, and its findings stop being checkable against the file.
- The principle list for the principles pass, and only that. It is the one pass whose subject is the list itself.
- The budget and the call at which the pass stops reading. Size it above the change: a starved pass returns a partial list that reads like a complete one, and an absent budget returns a pass that explores until its context fills. A generous budget still ends a pass that would otherwise run for hours.
- The reading boundary, as the changed files plus the exact-path allowance and the one named library exception. A delegate given no boundary keeps exploring until its context fills, and an unbounded pass costs tens of minutes on a single-digit-file change. Close the boundary against the network in the same sentence: a delegate with no stated limit fetches a library's source to settle a framework-semantics question, and one such excursion downloaded a gem release into a scratch directory while the answer was already in the repository.
- The machine-checkable exclusion, as its own sentence. Test execution, lint, and type-check results are CI's, so the brief names them as out of scope. Without that sentence a pass spends its budget repeating the pipeline and returns naming and formatting findings that CI already decided.

## Model

Pass `model: "claude-haiku-5-5"` and a high reasoning effort to every pass. The id is fixed, with no date suffix and no separate alias, so the skill does not go stale and there is nothing to pin forward. The effort is the half a surface drops silently: a Haiku pass left at the default effort reads shallowly and returns the findings the parent already explained away, so where a build takes no effort control, write `haiku-5-5/default` in the ledger rather than the bare id, and the reader then knows the effort was the surface default and not a choice.

If `claude-haiku-5-5` is unavailable on the surface running the review, an equivalent small model at high effort is allowed, and the ledger records the substitution, the model, and the effort that actually ran.

Do not fall back to the main model without saying so. A pass on the same model with the same context agrees with the parent reading, which is the exact failure delegation exists to avoid. A pass recorded as `skipped` is honest; a pass that ran on the same model and returned nothing is not evidence.

## Tools

Read, Grep, and Glob. No Bash, no Edit, no Write, no notebook or agent tools.

A delegate that wants a command names it in its return line and the main thread runs it. That keeps the delegate read-only, keeps its cost predictable, and keeps every write in the review under the operator's approval.

The reading boundary is a rule in the brief, and the narrow toolset is the second check on it. Neither replaces the acceptance rule below: a candidate that cannot be reproduced at the pin is dropped whether or not the delegate stayed inside its boundary.

## Return and acceptance

- Treat every returned finding as a hypothesis. It enters the report only when you reproduce the quoted line at the head commit yourself.
- Read `stopped_because` and `unread` before the findings. A pass that stopped at its budget answers on what it read, not on the change, so its silence about a surface is not evidence that the surface is clean. A return that omits `calls_used`, `stopped_because`, or `unread` is `partial` by definition, because there is no way to tell a complete pass from a truncated one.
- Drop a finding that arrives without a quoted line, a resolvable path, or an observed behaviour that differs from the expected one. Record the drop and its reason in the step ledger; a silent drop is indistinguishable from a pass that never ran.
- When a delegate raises a finding you already wrote, record it once and raise its confidence, noting that both passes found it.
- A delegate that returns nothing is recorded as "no candidate findings" with the files it read, the calls it used, and the model that ran.
- A delegate that did not read its reference, reviewed a different commit, or returned a summary instead of findings gets one corrected brief. A second failure is recorded as `partial` with the reason, and the step is not claimed complete.
- Never paste a delegate's prose into a review comment. Its value is the candidate. The comment is written in Google developer documentation style from your own verified reading, as Steps 5 and 6 require.

## The ledger

One line per pass, in the step ledger for Step 3:

```
3  principles    -               haiku-5-5/hi  4f2a91c  14 files  6 candidates, 3 kept, 3 dropped (<reasons>)  41/60 calls
3  domain        ruby-and-rails  haiku-5-5/hi  4f2a91c  11 files  4 candidates, 2 kept, 2 dropped (<reasons>)  58/60 calls, budget
```

- The line carries eight fields, in this order: the step (`3`), the pass (`principles` or `domain`), the domain (`-` for the principles pass), the model and effort (`haiku-5-5/hi`, `haiku-5-5/default`, or `same-model`), the head sha at seven characters, the files the pass read as `N files`, the candidate line as `N candidates, K kept, D dropped (<reasons>)`, and the calls used as `N/budget`, with `, budget` appended when the pass stopped at its call rather than at its conclusion.

A Step 3 line that names no model, no commit, no counts, and no call count is not a record of a pass.
