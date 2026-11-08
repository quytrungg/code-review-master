# Posting a review

Read this file before any write to the pull request. A review is read-only until the operator authorizes that write.

## Refresh before writing

Re-fetch the head, the review comments, and the reviews immediately before submitting:

```
gh pr view <n> --json headRefOid,state,mergedAt
gh api repos/OWNER/REPO/pulls/<n>/comments
gh api repos/OWNER/REPO/pulls/<n>/reviews
```

A reviewer or bot can post threads mid-review, so a comment list read at Step 0 is stale by the time you post. Classify the threads you find as fix, reply, stale, or duplicate. Reply on the existing thread instead of opening a second one for the same finding, and disclose the duplicate if you already posted one.

## Replying on an existing thread

A reply is a comment create carrying `in_reply_to`, not a second review:

```
gh api -X POST repos/OWNER/REPO/pulls/N/comments --input reply.json
```

```json
{"body": "Confirmed fixed at <sha>. ...", "in_reply_to": 4408600120}
```

`in_reply_to` takes the thread's **first comment id**. Build one JSON file per reply and post them in a loop, then confirm each by re-fetching `pulls/N/comments` and matching `in_reply_to_id` back to its parent; a reply that failed silently otherwise reads as a thread left unanswered.

**A re-review that resolves findings is one body review plus one reply per thread.** Post the replies first, then a body-only review whose body carries the per-finding classification — fixed, still valid, stale — against the new head. The pull request keeps a single dated summary, each thread closes on its own line, and the operator reads one table instead of six scattered notes. Keep the event at `COMMENT` when no blocking finding remains, and say which event you posted.

## One review, not N comments

```
gh api -X POST repos/OWNER/REPO/pulls/N/reviews --input payload.json
```

The payload carries `commit_id`, `event`, a short `body`, and a `comments` array of `{path, line, side: "RIGHT", body}`.

- One review is atomic and raises one notification.
- Because it is atomic, a single rejected anchor fails the whole request, so fall back to per-comment `pulls/N/comments` posts when partial success matters.
- Build the payload as JSON rather than a shell-quoted argument, since comment bodies are multi-line Markdown full of backticks.

## Match the event to the verdict

- `COMMENT` carries notes the author may act on.
- `REQUEST_CHANGES` blocks merge until every blocking finding is resolved or the review is dismissed.
- `APPROVE` belongs only to a head with no remaining blocking finding.

Say which event you posted. The posted state comes back as `CHANGES_REQUESTED`, so a delivery line that says "comments posted" hides the fact that the pull request can no longer merge without the author's action. A request to post every finding is not a request to block the merge: choose the event from the verdict, say which you posted, and name the findings you would gate on so the operator can raise it in one word.

**A `COMMENT` review posted under a second identity does not clear an earlier `CHANGES_REQUESTED`.** `reviewDecision` keeps reading `CHANGES_REQUESTED` and the pull request still cannot merge, so report that field after the write instead of a delivery line that implies the gate moved. Clearing it means dismissing that specific review (`PUT repos/OWNER/REPO/pulls/N/reviews/<review_id>/dismissals`); name it as the operator's action and do not run it unasked.

## Body versus inline

Inline comments are for defects in a changed line. An ask with no line to sit on goes in the `body`:

- revert a commit that does not belong in the pull request,
- update or rebase the branch onto its base, naming how far behind it is
  (`git rev-list --count <head>..origin/<base>`) rather than saying "update to latest",
- what was checked and found clean, so the author knows the silence is a result.

A finding the operator asks you to hold back as a defect becomes a corrective instruction in the body
instead of disappearing: name the commit, say what it does and where that change belongs. Keep the event
at `COMMENT` when the body carries only asks. A cross-cutting ask parked in an inline comment on an
unrelated hunk reads as a nit on that line and is lost.

## Every anchor must sit inside a hunk

GitHub rejects a comment on a line outside the diff's hunks. A pre-existing line in a modified file passes an at-head check and still fails the post.

```
git diff <base>...<head> -U0 -- <path>
```

- Check that the cited line falls inside one of the hunks.
- Anchor on an added line. Every line of a new file qualifies, and a large or generated file resolves the same way, from the hunks rather than from a search of the head copy.
- Never anchor on a file the pull request does not touch, however directly it causes the defect. Anchor on a changed file (the route's params block, the doc line that promises the contract) and name the untouched file in the body.

## Verify the write

Re-read `pulls/N/comments`, filter by `pull_request_review_id` for a review, and confirm each returned path and line.

- Parse those payloads defensively. The REST review and comment objects carry `user.login`, and a deleted account has no `user` key at all, so an `['author']` lookup imported from the `gh pr view` shape raises `KeyError` in the middle of verification.
- Report what landed with the id and URL for every comment.
- A successful `POST pulls/N/reviews` answers with `comments: []`, because that response does not expand inline comments. Take the count from the re-fetch, never from the post body.

## Approving

```
gh api -X POST repos/OWNER/REPO/pulls/N/reviews -f event=APPROVE -f commit_id=<head>
```

- Send no `body`; the review lands with an empty body.
- Before approving, confirm the pull request is open and unmerged (`state`, `mergedAt`) and that you are not its author, because GitHub rejects a self-approval.
- A bot author (an `app/...` login) does not block approval.
- `merged` is not a valid field; read `mergedAt`.

## When the head moves between the pass and the post

Re-verify every finding against the new head and post only the survivors.

1. Re-read `headRefOid` immediately before submitting.
2. When it differs from the commit the findings were verified against, fetch it, read `git diff OLD_SHA NEW_SHA` with the new commit subject, re-check each anchor, and drop every finding that commit fixed.
3. Name the dropped findings and the fixing commit in the review body so the author sees they were checked, and set `commit_id` to the head you verified.
4. Guard the post in the same command, so a move between the check and the write aborts instead of pinning the review to a stale commit:

```
LIVE=$(gh pr view N --json headRefOid --jq .headRefOid); [ "$LIVE" = "<verified>" ] && gh api -X POST ...
```

An instruction to post all findings means all findings that still hold at the live head.
