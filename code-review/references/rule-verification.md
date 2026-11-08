# Verifying a claim at the reviewed head

Step 4 rules. Each one decides whether a claim survives into the report. Read this file when Step 4 runs, not before.

## The general rule

Call a claim verified only when the check ran against the reviewed head and you can name the command or the file you read. A claim that changes the verdict gets re-read. A reviewer's or bot's severity label is not authoritative when the mechanism differs, so reclassify rather than inherit it: an availability or cost item that arrives labelled as a missing security control is still an availability item.

## Anchors and counts

- Reproduce each cited `path:line` at the reviewed head.
- Recount every number the report states (keys in a shape, files, lines) with a bounded command over the head copy. A claim that says 23 keys for a 22-key hash will also misjudge a parity claim resting on the same count.
- Check a cited line number against the file's length first. A citation past EOF means the diff was read, not the file, and the finding needs re-anchoring.

## Absence claims

Treat an absence claim as unproven until the whole file is read. A truncated diff window or a `head -n` excerpt is not the file, so "no test covers this path" and "no caller reads this param" are false when the rest was never read.

Re-run the search once in a second form before accepting a single empty result. A pattern that differs in case, sits under a path the pathspec excludes, or resolves through another module returns nothing while the definition exists:

```
git ls-tree -r --name-only <sha> | grep -i <name>
```

Confirm with the tree listing before writing "no such method".

## Diff markers

Decide that a line was **added** by this diff from the hunk, never from how the line reads. Content that is itself diff-shaped is indistinguishable from an addition in a plain diff read: an API Blueprint response is written `+ Response 403 (application/json)`, so a context line there and an added line look identical, and only a base comparison settles it:

```
gh api 'repos/OWNER/REPO/contents/PATH?ref=BASE_SHA' -H 'Accept: application/vnd.github.raw'
```

A "this pull request also changed an unrelated endpoint's docs" finding built on a misread marker is withdrawn material, and a withdrawn finding costs more trust than a missing one.

## Behaviour-change claims

Verify a "no behaviour change" or "unchanged when the flag is off" claim against the base revision, not the diff:

```
git show <merge-base>:<path>
```

Compare observable behaviour term by term: what renders, which request fires, with which params, on which path. A diff shows what was added and can never test a claim about what the base did. A new wrapper element that changes no behaviour is a documentation-accuracy note or a question, not a finding.

An optional parameter added server-side is inert until every caller sends it, so a server-only fix does not fix the user-visible path. `field_metadata` gained an optional `payroll_info_id`, and the web client's `useFetchFieldMetadata` still builds the URL with no query parameters and accepts only `onComplete` and `onFailed`, so the page keeps receiving the unfiltered fields. Read the client call site and either report the user-visible consequence as unverified or require the follow-up that names the caller; a merged server change alone is not evidence that the behaviour changed.

## Equivalence and cycle claims

An equivalence or cycle claim is settled by the mechanism, not by the resemblance.

- For an equivalence claim, compare the two outputs on identical inputs. A fallback that emits a bare name is not the builder branch that emits a name plus a count, and a requirement pinning the flag-off shape turns on exactly that difference, so accepting a "duplicated implementation" finding deletes a deliberate divergence.
- For a circular-import claim, read the other module's module-scope reads. A re-export list and a closure body are not evaluation-time reads, so a real cycle can still never throw. Refute the crash, and keep the layering inversion as its own finding instead of dropping both.

## Guards and mirrors

A missing cohort or permission guard is a finding only after its mirror surface is read. When a change adds a gate beside similar gates, a neighbour's exclusion comment describes that neighbour's feature, not a convention for every gate in the file. Read the surface whose data the new feature reads (the endpoint, service, card, or screen it mirrors) and match its cohort. Naming the mirror surface is what makes the finding checkable; without it the implementer adds a guard the product does not want, and the requirement that follows contradicts the surface the feature exists to match.

## Bodies and threads

Treat the pull request body as a claim pinned to the head revision, not as context to hand forward. A body can document a mechanism the head removed (a hook deleted by a later refactor, a renamed API), describe a signature that no longer exists, or carry a stale changed-file count. Verify its mechanism claims against head before they reach a finding, and report a stale body as a hygiene item rather than a code finding.

Check a prior thread the same way. A finding that quotes code absent from head is stale by mechanism even when the line it anchors to still resolves.

A body that lists a file the head does not contain is a missing-change finding when that file is what enforces the rule, not only a hygiene note. A description naming two migrations for a check constraint while the diff and `db/schema.rb` carry neither leaves the relaxed rule enforced by the model validation alone, which is a different contract from the one described. Reconcile the body's file list against `--json files`, then decide which of the two it is.
