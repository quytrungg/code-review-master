# Setting up a review

Step 0 rules. Read this file at the start of a pass, before reading any code.

## Pin the change

```
gh pr view <n> --json number,title,state,baseRefName,headRefOid,changedFiles,files
git fetch origin +refs/pull/<n>/head:refs/review/pr<n>
git rev-parse refs/review/pr<n>
git merge-base origin/<base> refs/review/pr<n>
```

- Fetch the head into a **named ref** and resolve it with `git rev-parse`. A plain `git fetch origin <ref-or-sha>` writes only `FETCH_HEAD`, which the next fetch overwrites: fetch the head, then the base branch, and `FETCH_HEAD` now points at the base tip, so `git merge-base origin/development FETCH_HEAD` returns that same tip and the diff comes back empty against something that is not the pull request at all. Assert the resolved commit equals `headRefOid` from `gh pr view` before reading anything, and quote that commit in every note.
- Treat `gh pr view <n> --json files` as the authoritative changed-file set. A file that exists at head but is absent from that list is a dependency, not a change, so do not report pre-existing behaviour in it as a finding.
- Compute the merge base against the pull request's own base branch, not against `main`.
- Resolve the base to a fetched remote ref before diffing. `git diff development...<head>` reads the checkout's `development`, which in a long-lived clone sits behind by weeks, so a three-dot listing against it names every merge the branch has since taken: hundreds of files for an eight-file pull request. Fetch first, then diff against `origin/<base>` or the merge-base commit, and reject the set unless its file count equals the count from `gh pr view <n> --json files`.

## A stacked change

A layer of a stack is reviewed against the layer it targets, not against `development`.

- Pin both ends: the layer's head and the parent head the layer claims. The merge base is between the two, and the base the review names is the parent branch.
- Prove the layer contains the parent: `git merge-base --is-ancestor <parent head> <layer head>`. Without it, a missing commit and a missing file are indistinguishable and the wrong one gets reported.
- Review `parent..layer`, and treat the parent's unlanded code as context rather than as this layer's change. A defect living in the parent gets one line in the review body naming the parent pull request, not an inline finding on a line this layer did not write.
- Verify the stack's final state once, at the top layer: a behaviour that is correct per layer can still be wrong when combined — two layers adding the same flag, index, or route, or an upper layer assuming a contract the lower one never shipped.
- When a layer cannot be judged without its parent merged, say that as an evidence gap and name the parent commit, rather than reviewing an imagined combined tree.
- State which layer, which parent commit, and which base the pass read.

## Read the change without touching the checkout

The checkout is often on another branch or dirty. Do not `checkout`, `reset`, or stash it. `git show <head>:<path>`, `git diff`, and `git merge-base` read fetched objects directly, so a branch switch is never needed to read one more file and can corrupt a tree another person is using.

- When `git show` cannot resolve the head, read the file through the API. `fatal: path '<path>' exists on disk, but not in '<sha>'` means the head commit was never fetched into the clone, not that the file is missing, and fetching the branch is not enough when the head is a squash or a branch tip the clone does not track:

```
gh api 'repos/OWNER/REPO/contents/PATH?ref=SHA' -H 'Accept: application/vnd.github.raw'
```

  Read the base revision the same way, with `ref=<base sha>`.
- Never derive a finding from the working-tree copy of an ownership or oversized config file. The tree sits on a different branch, so it carries merges the pull request does not: two slices that each add the same ownership block give duplicated lines in the tree and none in the pull request. A "duplicate entry" or "missing entry" claim built from `grep <path>` against the tree is a false finding until `git show <head>:<path>` reproduces it. The same trap applies to a file the pull request adds, whose tree copy may contain later slices from the same epic.
- When you search an ownership or config file for one symbol, search the plural and path-form names too. An ownership directory pattern carries the plural name (`/app/services/open_api/contractor_unavailabilities/`), so a singular `grep contractor_unavailability` misses those entries and reads as "no duplicates present". Count the lines the hunk adds and reconcile that count against what the search returned before concluding anything.
- A refused fetch is usually background maintenance, not a second writer. `Another git process seems to be running in this repository, or the lock file may be stale` arrives while `git maintenance run --auto` or `git repack` runs, which macOS launches on its own schedule. Check `ps aux | grep -E 'git (repack|maintenance)'`, list `.git/*.lock`, and compare `.git/index` mtime against the last recorded write before concluding that another writer owns the tree. When the only process is maintenance, wait a few seconds and re-run.

## What to read and what to skip

- Leave oversized generated files out of the reading set: `CODEOWNERS`, lockfiles, generated bundles, and translation catalogues (`config/locales/*.yml` runs from 100 KB to 1.4 MB, and a `CODEOWNERS` can run to a megabyte). Keep them in the diff only and read them by targeted search.
- Read the immediate dependencies a finding will rest on: the parent class, the sibling surface being ported from, the serializer, and the scope or policy the change calls.
- For a frontend change (`frontend-core`, `eh-mobile-pro`) the dependencies are framework files rather than gems: `libs/api/src/lib/useApi.ts` for loading, data, and error semantics; the relevant `apps/hr-web-app/src/packages/eh-utils/*` helper when the change leans on a shared predicate (`data.ts` for a `dataReadyHandler`-style ready check); and `apps/hr-web-app/__mocks__/@testing-library/react.js` for the configured `testIdAttribute`. Locating those mid-review turns the pass into a search and then forces a guess at the ready and failure semantics the finding rests on.
- Read the source of the organisation's own gems a finding may rest on, at the version the lockfile pins: `$(gem env gemdir)/gems/<gem>-<version>/lib`. The allowlist is `eh_protobuf` and `eh-keypay`; no other library's source is read, and a claim that needs one is returned as unread with the library and version named. The Ruby mechanics that use those shapes are in `references/rails-change-traps.md`.
- Pull the existing threads so each finding is classified against them instead of duplicated: `gh api repos/OWNER/REPO/pulls/<n>/comments` and `gh api repos/OWNER/REPO/pulls/<n>/reviews`.
- For a leave-domain change, the leave wiki at `Thinkei/leave-llm-wiki` is a reading dependency, and it is read one page at a time: `gh api 'repos/Thinkei/leave-llm-wiki/contents/wiki/<page>.md?ref=<sha>' -H 'Accept: application/vnd.github.raw'` fetches the page the change is about at a pinned commit, rather than the tree or a recursive search. Quote the page and the commit in the review. The repository is private to the organisation and a delegated pass has no network, so the parent reads it and the ledger records the page, the commit, and that the pass returned the question unread. A page older than the change it is cited against is context, not evidence.
- When a pass spans two repositories, record the absolute path of the repository that owns each group of files and repeat the read-only command per repository. A note that mixes roots makes the next reader search the wrong tree, report it as unavailable, and downgrade every question that depended on it from a finding to a question.

## Reading a run against the change

A run is evidence only for the revision it executed against. CI pins that revision by construction, so a test, type-check, or lint result is read from the head commit's own checks (`references/test-and-lint-evidence.md`) rather than reproduced here: this review runs no suite, no type-check, and no lint, and creates no worktree to reach one.

- The trap is a result quoted from a tree that does not contain the head. When a body, a comment, or the operator quotes a run from a developer machine, establish its revision before the number: `git -C <repo> diff --stat HEAD <head> -- <changed paths>` is non-empty when the checkout does not contain the pull request, and a changed module missing from the tree altogether is the same signal. A green focused run against the wrong revision is more misleading than no run at all.
- Report the result as an evidence gap when its revision cannot be established, naming the branch the tree was on and what the diff showed. A run against one revision is a simulation for the head, not a gate on it.

## Re-review

When the head moved, review the delta and keep the full `base...head` diff as secondary context.

- Compare the recorded reviewed commit against the live head and confirm both it and the base; a rebase moves the base.
- A saved review record looks current while pinned to the commit it was built from, so confirm its recorded commit against the live pull request before reusing anything in it.
- Classification of every earlier finding is FIXED, STILL VALID, or STALE against the current head, quoting current lines. A fix commit's message and file list are not evidence that a finding was resolved.
- Re-read in full when the new commits add a file, change the base, or move a file a finding anchors to. When they touch only files the first pass read, the delta alone is enough.
