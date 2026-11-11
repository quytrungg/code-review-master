"""Prompt construction: local skills as the system contract, numbered diff as the task."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.diff_parser import FileDiff

# Marker inserted where a file lost whole hunks to the budget, so the model is told what is missing
# rather than inferring that the file ends there.
OMITTED_HUNKS_MARKER = "[… {count} further hunk(s) of this file omitted …]"


@dataclass
class UserPrompt:
    """One built prompt plus what the budget had to drop to build it."""

    text: str
    truncated: bool = False
    # "path (last N hunk(s))" per file that did not fit whole.
    omitted: list[str] = field(default_factory=list)


def render_file_block(item: FileDiff, max_chars: int | None = None) -> tuple[str, int]:
    """`## File:` heading plus its numbered hunks, cut on hunk boundaries.

    Returns `(block, dropped_hunks)`. `max_chars` bounds the block; when it does not fit, whole
    hunks are dropped from the end — a half-rendered hunk would show the model line numbers for
    code it cannot see. The one exception is a first hunk that alone overflows the budget: nothing
    else could be shown either, so it is cut (as the old single-call path did) and reported.
    """
    head = f"## File: {item.path}  (+{item.added}/-{item.removed})\n"
    rendered: list[str] = []
    used = len(head)
    dropped = 0
    for index, hunk in enumerate(item.hunks):
        text = hunk.render_numbered()
        if max_chars is None or used + len(text) + 1 <= max_chars:
            rendered.append(text)
            used += len(text) + 1
            continue
        room = max_chars - used
        if not rendered and room > 500:
            rendered.append(text[:room] + "\n[… hunk truncated here …]")
        dropped = len(item.hunks) - index
        break
    if dropped:
        rendered.append(OMITTED_HUNKS_MARKER.format(count=dropped))
    return head + "\n".join(rendered) + "\n", dropped


def file_block_size(item: FileDiff) -> int:
    """Rendered size of a file's block with no budget applied — what `plan_units` packs."""
    return len(render_file_block(item)[0])


OUTPUT_CONTRACT = """
# Output contract

Return ONLY a JSON object — no prose, no markdown fences, no text before or after it:

{
  "verdict": "APPROVE" | "COMMENT" | "REQUEST_CHANGES",
  "confidence": 0,
  "findings": [
    {
      "filePath": "path/to/file.ext",
      "lineNumber": 42,
      "diffHunk": "@@ -40,7 +40,7 @@ ...the surrounding lines, copied from the diff...",
      "initialComment": "Markdown explanation of the defect, at most 120 words."
    }
  ]
}

`verdict` is your opinion about the whole pull request:
- `REQUEST_CHANGES` when at least one finding must be fixed before merge,
- `COMMENT` when the findings are worth raising but nothing blocks the merge,
- `APPROVE` when the change is safe as it stands.

`confidence` is an integer 0-100: how sure you are that this verdict is right given what you
could see of the diff. Use lower numbers for truncated diffs or unfamiliar code.

Rules for findings:
- Report only defects you can point at one specific changed line: a bug, a security or data
  issue, a broken contract, a missing test for a risky path, or a clear maintainability trap.
- `lineNumber` must be a number printed in the LEFT column of the numbered diff below. Never
  invent a line number, and never cite a deleted line (those rows have no number).
- `filePath` must be copied verbatim from a file heading in the diff.
- `diffHunk` must quote the lines around `lineNumber` exactly as they appear in the diff.
- Write `initialComment` in Markdown: what is wrong, why it matters, and the concrete fix.
  Lead with severity (Critical / High / Medium / Low). Do not pad with praise or summary.
- Do not report anything a formatter, linter, or type checker decides.
- If the change is clean, return an empty `findings` array with `"verdict": "APPROVE"`.
""".strip()


def build_system_prompt(skills_text: str) -> str:
    parts = [
        "You are a senior software engineer reviewing a GitHub pull request. You apply the",
        "repository's own review standards, supplied below, and you report only findings that",
        "are anchored to a specific line of the diff.",
        "",
        skills_text.strip()
        or "# Review standards\n\nNo local skill files were found; apply rigorous, general engineering judgement.",
        "",
        OUTPUT_CONTRACT,
    ]
    return "\n".join(parts)


def build_user_prompt(
    pr,  # pull_request.PullRequestInfo (kept loose to avoid a circular import)
    files: list[FileDiff],
    max_chars: int,
    *,
    part: int | None = None,
    total: int | None = None,
) -> UserPrompt:
    """Numbered diff with the change-request header, bounded by `max_chars`.

    `part`/`total` add the multi-pass framing: a part is told which files it owns and that other
    parts cover the rest, so it does not speculate about code it was not given.
    """
    separator = "#" if getattr(pr, "vcs", "github") == "github" else "!"
    header = [
        f"# Pull request {pr.project}{separator}{pr.number}: {pr.title}",
        f"- State: {pr.state}{' (draft)' if pr.draft else ''}",
        f"- Author: {pr.author}",
        f"- Changed files: {len(files)} reviewable, +{sum(f.added for f in files)}/-{sum(f.removed for f in files)}",
    ]
    if part and total and total > 1:
        header.insert(3, f"- This prompt covers part {part} of {total} of the change")
    if pr.body:
        body = pr.body.strip()
        if len(body) > 1500:
            body = body[:1500] + "…"
        header.append(f"- Description:\n{body}")
    header.append("")
    header.append("# Diff (left column = RIGHT-side line number; use only these numbers)")
    header.append("")
    if part and total and total > 1:
        names = ", ".join(f"`{item.path}`" for item in files)
        header.append(
            f"NOTE: this is part {part} of {total} of a large pull request, split by file. Report "
            f"findings only in these files: {names}. Do not report on, or speculate about, files "
            "that are not shown here; other parts cover them."
        )
        header.append("")

    chunks: list[str] = []
    omitted: list[str] = []
    used = 0
    truncated = False
    for item in files:
        block, dropped_hunks = render_file_block(item, max_chars - used)
        chunks.append(block)
        used += len(block)
        if dropped_hunks:
            truncated = True
            omitted.append(f"{item.path} (last {dropped_hunks} hunk(s))")
            break

    if truncated:
        header.append(
            "NOTE: the diff was truncated to fit the model context. Review what is shown and do "
            "not speculate about files that are missing."
        )
        header.append("")

    return UserPrompt(text="\n".join(header) + "\n".join(chunks), truncated=truncated, omitted=omitted)


DISCUSSION_CONTRACT = """
# Your role now

You are continuing a review conversation about one specific finding. The reviewer may ask why
you flagged something, disagree, or propose an alternative.

- Answer in at most 150 words of Markdown.
- Concede plainly when the reviewer is right, and state the corrected recommendation.
- Hold your position when the reviewer is wrong, and name the concrete risk that remains.
- Do not restate the whole finding, and do not add new unrelated findings.
- You cannot publish, withdraw or delete a finding, and you cannot change what apply posts: the
  reviewer decides with **Accept** or **Push back** on each round. Never say a finding was removed.
- Never wrap the answer in JSON.
""".strip()


def build_discussion_system_prompt(skills_text: str) -> str:
    return "\n".join(
        [
            "You are a senior software engineer discussing a code review finding with a colleague.",
            "",
            skills_text.strip()
            or "# Review standards\n\nNo local skill files were found; apply rigorous, general engineering judgement.",
            "",
            DISCUSSION_CONTRACT,
        ]
    )


def build_discussion_user_prompt(
    pr_repo: str, pr_number: int | None, thread, references=None
) -> str:
    """PR identity + anchored hunk + full transcript (+ any `#N` references) for one thread."""
    header = [
        f"# Pull request {pr_repo}{f'#{pr_number}' if pr_number else ''}",
        f"- Finding anchored at: `{thread.file_path}:{thread.line_number}`",
        "",
        "## Diff context",
        thread.diff_hunk or "(no diff context stored)",
        "",
        "## Conversation so far",
    ]
    authors = {
        item.round_number: item.inbound_author
        for item in getattr(thread, "rounds", [])
        if item.inbound_author
    }
    current_round: int | None = None
    for message in thread.messages:
        number = getattr(message, "round_number", 1) or 1
        if number != current_round:
            header.append(f"## Round {number}")
            current_round = number
        if getattr(message, "is_external", False):
            author = authors.get(number)
            speaker = f"GitHub comment by @{author}" if author else "GitHub comment"
        elif message.role == "user":
            speaker = "Reviewer (user)"
        elif message.role == "system":
            speaker = "System"
        else:
            speaker = "You (assistant)"
        header.append(f"### {speaker}\n{message.content}")
    header.append("")

    if references:
        from app.services.references import format_references_block

        header.append(format_references_block(references))
        header.append("")

    header.append("Reply to the reviewer's last message.")
    return "\n".join(header)


MAX_VERDICT_THREADS = 40
MAX_VERDICT_MESSAGE_CHARS = 900

VERDICT_CONTRACT = """
# Task

This change has already been reviewed and discussed. Decide the verdict you would publish now.

Return ONLY this JSON object:

{"verdict": "APPROVE" | "COMMENT" | "REQUEST_CHANGES", "confidence": 0-100,
 "rationale": "one sentence, at most 30 words"}

Rules:
- `REQUEST_CHANGES` while an unresolved finding still blocks merging.
- `COMMENT` when the remaining concerns are minor or informational.
- `APPROVE` when every raised issue was resolved or withdrawn during the discussion.
- `confidence` is how sure you are of that verdict, 0-100, based on how conclusive the threads are.
- `rationale` names the deciding factor in one sentence: no markdown, no line breaks.
""".strip()


def _verdict_excerpt(text: str) -> str:
    body = " ".join((text or "").split())
    if len(body) > MAX_VERDICT_MESSAGE_CHARS:
        body = body[:MAX_VERDICT_MESSAGE_CHARS] + " […truncated]"
    return body or "(empty)"


def build_verdict_prompt(threads) -> str:
    """Every thread's original finding and latest conclusion, for one verdict decision."""
    parts = [f"# Review state — {len(threads)} thread(s)", ""]
    for ordinal, thread in enumerate(threads[:MAX_VERDICT_THREADS], start=1):
        withdrawn = " (withdrawn during discussion)" if getattr(thread, "dropped", False) else ""
        parts.append(f"## #{ordinal} `{thread.file_path}:{thread.line_number}`{withdrawn}")
        assistant = [m for m in thread.messages if m.role == "assistant"]
        if assistant:
            parts.append(f"Original finding: {_verdict_excerpt(assistant[0].content)}")
            if len(assistant) > 1:
                parts.append(f"Latest conclusion: {_verdict_excerpt(assistant[-1].content)}")
        reviewer = [m for m in thread.messages if m.role == "user"]
        if reviewer:
            parts.append(f"Reviewer's last message: {_verdict_excerpt(reviewer[-1].content)}")
        parts.append("")

    if len(threads) > MAX_VERDICT_THREADS:
        parts.append(f"({len(threads) - MAX_VERDICT_THREADS} further thread(s) omitted.)")
        parts.append("")
    parts.append(VERDICT_CONTRACT)
    return "\n".join(parts)


def build_findings_verdict_prompt(findings) -> str:
    """The merged findings of a multi-part review, for one verdict decision.

    Used when the review was split: each part returns its own opinion about the slice it saw, and
    none of them saw the whole change. This pass is the one that sees every finding at once.
    """
    parts = [f"# Review state — {len(findings)} finding(s)", ""]
    for ordinal, finding in enumerate(findings[:MAX_VERDICT_THREADS], start=1):
        parts.append(f"## #{ordinal} `{finding.path}:{finding.line_number}`")
        parts.append(f"Finding: {_verdict_excerpt(finding.comment)}")
        parts.append("")

    if len(findings) > MAX_VERDICT_THREADS:
        parts.append(f"({len(findings) - MAX_VERDICT_THREADS} further finding(s) omitted.)")
        parts.append("")
    parts.append(VERDICT_CONTRACT)
    return "\n".join(parts)
