# Maintaining this skill

The canonical copy lives in the skill hub repository under `skills/code-review/`. Find the checkout and the hub's own commands through the hub's instructions rather than a remembered path. Every installed copy is a copy of that directory, so an edit belongs in the hub copy followed by a reinstall; an edit made to an installed copy is lost at its next install.

## Which file a rule belongs in

| Subject | File |
|---|---|
| Step order, contract, classification, guardrails | `SKILL.md` |
| Reading the change, fetch, base, re-review delta | `references/review-setup.md` |
| Whether a claim is true at the head | `references/rule-verification.md` |
| Test and lint evidence | `references/test-and-lint-evidence.md` |
| Finding record, severity, decision posture, evidence authority | `references/review-rubric.md` |
| Rails, Grape, Active Record mechanisms | `references/rails-change-traps.md` |
| Ruby and Rails: the router that chooses a subject set | `references/ruby-and-rails-review.md` |
| Ruby and Rails subject rules, one file each | `references/ruby-and-rails/*.md` |
| Leave domain rules | `references/leave-domain-review.md` |
| Reports domain rules: main app, custom reports (BYOR), reports-service, frontend reports module | `references/reports-domain-review.md` |
| Frontend rules both surfaces share | `references/frontend-shared-review.md` |
| Web-only frontend rules | `references/frontend-review.md` |
| React Native-only rules | `references/mobile-review.md` |
| Prose style for review comments | `references/google-style.md` |
| Output shape, plain-language edit, fix-versus-push-back | `references/output-and-drafting.md` |
| Posting, events, anchors, write verification | `references/github-review-posting.md` |
| Delegating the two passes, briefs, reading boundary, acceptance | `references/domain-delegation.md` |
| File-to-subject map, rule bar, vocabulary, verification | `references/maintaining-this-skill.md` |

Two structural rules follow from that table. A rule that applies to both web and mobile belongs in `frontend-shared-review.md`; a surface file repeats nothing the shared file already states. And a new reference must be added to the routing table in `SKILL.md` in the same change, because a file no step names is never read.

A rule set that outgrows one file ships as a router plus subject files, as the Ruby set does: the router carries the table that selects a subject for a change, and each subject file carries one class of rule. Add a new subject to the router's table in the same change that adds the file, and keep `essential-checks.md` small enough to ride along with every subject, because it is the one file a change of any kind reads.

## The bar for a new rule

Admit a rule only when it names the primitive, the exact wrong expression, the failure it causes, and the suppression that stops the resulting false positive. A rule a competent reviewer would already apply without this skill adds prose rather than capability.

- Name the primitive: a prop, hook, helper, command, column, config key, error string, or threshold.
- State the wrong expression literally, quoted from code or a command.
- State the consequence, in the terms the reader can check: a wrong balance, a dropped event, a silently granted access, a run that proves nothing.
- State the suppression, so the rule does not fire on the cases that are deliberate.
- Keep one rule per bullet and keep its reason in the same bullet. A bare imperative loses the mechanism the next reader needs to judge a new case.
- Prefer the observed mechanism to a principle. When a candidate cannot name a file, symbol, or command, it is not ready to land.
- Domain rules only. How a review is run belongs in `SKILL.md` or its step references, never in a domain file.

## Vocabulary the files must not carry

These files read as team engineering guidance. Keep them that way:

- No provenance. Never state where a rule came from: no "collected from", "we found in past reviews", corpus or snapshot framing, and no reference to a source document behind a rule. An incident key (`WM-6020`, `CXP-18929`) is evidence a reviewer can chase, not provenance, so it stays — but it never replaces the described consequence. A named organisation repository is the one permitted domain reference: `https://github.com/Thinkei/leave-llm-wiki` is cited by URL, by the page inside it, and by the pinned commit, because a reviewer is expected to read it. Cite it beside the mechanism and never instead of it, so the rule survives the repository moving.
- No machine paths. No home-directory paths, no path to a checkout, no path to a packaged skill. Resolve a toolchain location from the tool itself, as `$(gem env gemdir)` does.
- No personal framing. Rules are the team's, so no first person and no reviewer's name.
- No other vendor's names. This skill runs in Claude Code and names the Task tool and the `haiku` alias on purpose, so those stay; names of other vendors' assistants, editors, or platforms do not appear. Internal process words do not appear either: lane, wave, fan-out, and child are out. "Budget" is allowed in one narrow sense, the tool-call budget that ends a pass, because Step 3 depends on it. "Delegate", "pass", and "subagent" are allowed, because Step 3 is a delegated pass.
- No references to helper programs this skill does not ship.
- Domain senses of the same words are fine and must stay, because they carry the mechanism: a database session timezone, a JWT session claim, a lag budget, a rollout wave, a payroll event dispatched to a provider, a `kill_switch` config key, a React `dispatch`, `Time.zone.local`, `AGENTS.md`.

Check a change with a word-boundary sweep, not a substring sweep: a substring match flags the words hidden inside longer ones (`description` and `descriptive` both contain a word this file forbids). Every surviving hit is justified in the change description by quoting its line.

## Rules that come from the organisation's rule catalogue

Some sections restate a rule the organisation publishes in its own guidance repository. When adding one:

- Keep the rule identifier in the section heading, as `(org rule `#EH-...`)`, so a reader can trace the requirement back to the catalogue.
- Drop everything the source carries for a specific tool: frontmatter, path globs, and any instruction to tag comments. Those belong to that tool's config, not to this skill.
- Keep the mechanism and the measured consequence, and drop the tool-specific examples that only restate them.
- Reconcile, do not overwrite. Where an imported rule contradicts a rule already in the file, decide which applies to which case and write both: the catalogue is the contract, and the existing rule usually describes an older path that still exists. Say in the bullet which case each one covers.

## Changing or withdrawing a rule

- Change the rule where it lives, then search every file for the old phrasing. A corrected rule does not propagate on its own, and the stale wording survives in a sibling until the next reader copies it.
- When a rule is withdrawn, correct the requirement it rested on in the same change. A written criterion still demanding the withdrawn behaviour fails a correct implementation later.
- When a rule moves between files, update the routing table and the file it left in the same change, and delete the old copy rather than leaving both.
- Bump `version` in `SKILL.md` when a rule set, a reference file, or the routing changes. A wording fix inside one bullet does not need a bump.

## Verify a change before landing it

1. The routing table lists every reference file, and every listed path resolves. `tests/test_code_review_rules.py` asserts this in both directions, so a reference no row reaches fails the suite instead of going unread.
2. A rule you changed is findable by its distinctive identifier in the file that owns its subject.
3. The word-boundary sweep reports only justified hits. The same test module fails a machine path in any of these files, which is the one category of hit no justification can rescue.
4. The hub repository's own two gates pass, run from its root: `python3 scripts/eh-skill-hub validate` and `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests`. The reference checks above run inside that second command; run `python3 -m unittest tests.test_code_review_rules -v` alone while editing. Then `find . -name __pycache__ -print` prints nothing.
5. Reinstall the entry for each configured surface and prove the installed copy matches the hub copy with a directory diff. An install summary is not parity evidence.
