# Output, drafting, and the fix-versus-push-back split

Step 6 rules. Read this file when the findings are settled and the review is about to be written.

## The finding record

Grade and validate every finding against `references/review-rubric.md` first: the nine-field record, the severity table, and the decision posture live there. The list below is the output shape, not a second record.

- Findings first, ordered by severity and confidence, then conditional questions, then evidence gaps.
- Format each finding as `[severity] Consequence-oriented title — path:line`.
- Then state the record's fields in compact prose: trigger, reachable path and consequence, expected contract with its evidence class, the guards and tests checked, and the smallest viable correction.
- Quote the source line beside each `path:line` so the finding is verifiable without re-reading the file.
- Keep attribution separate: repository contract, general engineering rule, observed author pattern.
- When nothing survives, say so explicitly and list the material evidence gaps.

## The durable file

Write the settled review to a durable file in the review folder before asking about posting, and open it with the step ledger.

Write it once, at synthesis. A provisional draft has to be fully re-read before it can be overwritten, which costs turns; hold early findings in notes and write the review file when the findings are settled. Step 3 still requires your own findings before the delegate briefs, and that ordering tempts an early write to the durable file: keep them in scratch notes instead, because a file read with `offset`/`limit` and then edited refuses the later whole-file write, so an early draft costs a full re-read before synthesis can land.

## Explain the whole finding

When the operator asks you to explain a finding, explain all of it: what the code does, what its contract claims, the failure path, why the severity is what it is, and the smallest fix. Expanding only the one technical term in the title answers a narrower question than the one asked and draws a repeat.

## Confirm the split before posting

Present the numbered finding list with the `path:line` anchor each comment will land on, plus a recommended post-or-defer split.

- Post only the subset the operator approves, and state which findings you deferred.
- Every deferred or skipped item carries its reason on the same line ("folds into 1 and 3", "unverified convention", "follow-up"), because a bare skip reads as an oversight and costs a round trip.
- When the operator overrides the split, post the set they named without re-arguing the recommendation.
- **A fix round moves the split again.** Once the findings are addressed, the operator may call what remains too small to post at all. Then do not open a second review round for those items and do not re-argue them: state each in one line in the acceptance or handoff record, so it survives as known-and-not-fixed instead of vanishing. A second review carrying title-level nits costs a round trip and reads as reluctance to close.
- Record **why** a finding left the set, because three different causes read identically in a reply that only says "dropped": refuted by source (name the mechanism), withdrawn as unsound, or dropped because the operator said no. The last one is an instruction, not a verdict on the finding, and the operator will come back asking whether it was valid. Carry the distinction in the sentence that drops it — "dropped at your instruction; on the merits it would be Low" — rather than reconstructing it afterwards, and never let a drop-by-instruction read as agreement that the item was wrong.

## The plain-language edit

Apply this to every synthesized comment, and put the receipt in the step ledger. Rewrite:

- Inflated words (crucial, pivotal, delve, landscape, testament, underscore, showcase, vibrant, intricate) to plain equivalents.
- Sales language and vague sources to the concrete evidence, named.
- "Serves as", "stands as", "boasts" to "is" or "has".
- A second em dash or more in one comment to a comma, colon, or period; keep a single one where it joins two clauses and reads faster than a full stop. An en dash becomes a hyphen or a comma, never an em dash.
- Forced groups of three and "not X but Y" constructions to the specific claim, restated.
- Bold-heavy list items with bold mini-headings, decorative emojis, and curly quotes to plain formatting, sentence case, straight quotes.
- Agreeable openers to the finding itself, starting the comment.
- Filler and stacked qualifiers ("in order to", "due to the fact that", "it is important to note that") to the shortened phrase, keeping a qualifier only when the evidence needs it.
- Generic positive endings to the last concrete fact.

Preserve every factual claim and file reference, and keep quoted code, identifiers, and error messages verbatim. Rewrite prose only. When the edit is skipped, say so in the delivery message rather than marking the step complete.

## Fix versus push back

When the operator asks what to fix and what to push back on, deliver a decisive split, not a summary.

- **Fix:** each item with the smallest action and the line to change. Include a contract or security item even when it is not a live leak, when the repository's standards (strict contracts, explicit authorization) call for it.
- **Push back:** each item with the code evidence that defeats or downgrades it. Reclassify a label that does not match the mechanism, and say when a fix would create a divergence from a sibling surface.
- Withdraw a question once source answers it. Trace the symbol to its definition instead of shipping the question: a path parameter is decorative only if no helper reads it, so check the resolver that reads it (a `current_organisation`-style helper) before asserting it is ignored.
- Withdraw a finding when source refutes it, and correct the requirement it rested on in the same pass. A finding that traces back to a written criterion leaves the criterion still demanding the wrong behaviour, so the gate later fails a correct implementation; patch the criterion and say in one line that both moved. Do not soften the finding into a suggestion to avoid the retraction.
- Separate a true observation from a remedy a written criterion forbids. When what a finding describes is real but the proposed fix would break the ticket's own acceptance criterion — the criterion says the key names only the worker type and the flag, and the fix would AND in a cohort term the design deliberately keeps as a separate gate — quote the criterion and decline the remedy. The observation stands, the cure does not, and those are two different verdicts. Then re-home the check: a rule about a consumer that is not in this diff belongs on the pull request where that consumer appears, so name that PR instead of filing the producer as defective.
- Defer maintainability items that are not merge blockers to a follow-up, and say so explicitly.
- Keep it to two short lists; do not restate the findings.
