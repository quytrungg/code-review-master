"""Deterministic pre-pass checks: things a regex knows for certain, at zero tokens.

The model is the analysis layer; these packs exist for the cases where it is weakest and the cost
of missing them is highest — a committed credential, a private-key header, a conflict marker, a
debugger left in, a focused test. A pack is **data** (id, label, rules) so adding a pattern never
means touching the pipeline, and the set stays at "a reviewer would block the PR for this": no
style rules, no TODO notes, no entropy heuristic that flags every hash and fixture.

Findings are converted into `RawFinding`s and anchored by the pipeline through the same
`anchor_findings` path as model output, so a check can never point at a line the diff lacks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.review import ThreadOrigin
from app.services.diff_parser import ADD, FileDiff

# Paths where a key-shaped string is usually a deliberate fake. Matched as lower-case substrings.
FIXTURE_PATH_HINTS = (
    "/test/",
    "/tests/",
    "/spec/",
    "/__tests__/",
    "/fixtures/",
    "fixtures/",
    "conftest.py",
    "test_",
    "_test.",
    ".test.",
    ".spec.",
    "mock",
    "example",
)

TEST_PATH_HINTS = ("/test/", "/tests/", "/spec/", "/__tests__/", "test_", "_test.", ".test.", ".spec.")


@dataclass(frozen=True)
class Rule:
    id: str
    pattern: str
    severity: str
    message: str
    # Scan only paths containing one of these; empty means every path.
    path_hints: tuple[str, ...] = ()
    # Never scan paths containing one of these (fixtures carrying fake keys).
    skip_path_hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class Pack:
    id: str
    label: str
    description: str
    max_per_review: int
    rules: tuple[Rule, ...]


PACKS: tuple[Pack, ...] = (
    Pack(
        id="secrets",
        label="Secrets",
        description="Known token prefixes, cloud access keys and private-key headers.",
        max_per_review=10,
        rules=(
            Rule(
                id="github-token",
                pattern=r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b",
                severity="Critical",
                message=(
                    "A GitHub token looks committed here. Revoke it in GitHub, move the value to "
                    "an environment variable, and purge it from the history."
                ),
                skip_path_hints=FIXTURE_PATH_HINTS,
            ),
            Rule(
                id="aws-access-key",
                pattern=r"\bAKIA[0-9A-Z]{16}\b",
                severity="Critical",
                message=(
                    "An AWS access key id looks committed here. Deactivate the key in IAM and "
                    "load it from the environment instead."
                ),
                skip_path_hints=FIXTURE_PATH_HINTS,
            ),
            Rule(
                id="private-key",
                pattern=r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                severity="Critical",
                message=(
                    "A private key is being added to the repository. Rotate the key and keep it "
                    "in a secret store, never in a tracked file."
                ),
            ),
            Rule(
                id="openai-key",
                pattern=r"\bsk-[A-Za-z0-9_-]{20,}\b",
                severity="Critical",
                message=(
                    "A provider API key looks committed here. Revoke it, load the value from the "
                    "environment, and remove it from the history."
                ),
                skip_path_hints=FIXTURE_PATH_HINTS,
            ),
        ),
    ),
    Pack(
        id="hygiene",
        label="Hygiene",
        description="Conflict markers, debugger statements, console logging and focused tests.",
        max_per_review=10,
        rules=(
            Rule(
                id="conflict-marker",
                pattern=r"^(?:<{7}(?: |$)|={7}$|>{7}(?: |$))",
                severity="High",
                message=(
                    "A merge-conflict marker is being added. Resolve the conflict and remove the "
                    "markers before merging."
                ),
            ),
            Rule(
                id="debugger",
                pattern=r"(?:\bdebugger\b|\bbreakpoint\(\)|\bbinding\.pry\b|\bbyebug\b)",
                severity="Medium",
                message=(
                    "A debugger statement or breakpoint is left in the change. Remove it before "
                    "merging."
                ),
            ),
            Rule(
                id="console-log",
                pattern=r"\bconsole\.log\(",
                severity="Low",
                message="A console.log call is left in the change. Remove it or use the app's logger.",
            ),
            Rule(
                id="focused-test",
                pattern=r"\.(?:only|skip)\(",
                severity="Medium",
                message=(
                    "A focused or skipped test is committed. It silently removes coverage from "
                    "the suite; remove the marker or say why the test is skipped."
                ),
                path_hints=TEST_PATH_HINTS,
            ),
        ),
    ),
)

PACK_IDS = frozenset(pack.id for pack in PACKS)
_PACK_BY_ID = {pack.id: pack for pack in PACKS}
_COMPILED = {
    (pack.id, rule.id): re.compile(rule.pattern, re.MULTILINE)
    for pack in PACKS
    for rule in pack.rules
}


@dataclass
class CheckFinding:
    """One deterministic hit, anchored to a real added line."""

    path: str
    line_number: int
    comment: str
    pack: str
    rule: str
    origin: str = ThreadOrigin.CHECK


def pack_registry() -> list[dict[str, str]]:
    """What `GET /api/settings` exposes so the page renders from data, never a hardcoded list."""
    return [
        {
            "id": pack.id,
            "label": pack.label,
            "description": pack.description,
        }
        for pack in PACKS
    ]


def enabled_packs(configured: list[str] | None) -> list[Pack]:
    """Configured ids, in registry order; unknown ids are ignored (the route rejects them)."""
    wanted = set(configured or [])
    return [pack for pack in PACKS if pack.id in wanted]


def _applies(rule: Rule, path: str) -> bool:
    lowered = path.lower()
    if rule.skip_path_hints and any(hint in lowered for hint in rule.skip_path_hints):
        return False
    if rule.path_hints and not any(hint in lowered for hint in rule.path_hints):
        return False
    return True


def _comment(pack: Pack, rule: Rule) -> str:
    return (
        f"{rule.severity} — {rule.message}\n\n"
        f"_Deterministic `{pack.id}` check (`{rule.id}`); no model call was used._"
    )


def scan(
    files: list[FileDiff], packs: list[Pack], warnings: list[str] | None = None
) -> list[CheckFinding]:
    """Find every rule hit on an added line, capped per pack and de-duplicated per line."""
    findings: list[CheckFinding] = []
    seen: set[tuple[str, int, str]] = set()
    for pack in packs:
        hits = 0
        capped = False
        for item in files:
            for hunk in item.hunks:
                for line in hunk.lines:
                    if line.kind != ADD or line.new_no is None:
                        continue
                    for rule in pack.rules:
                        key = (item.path, line.new_no, rule.id)
                        if key in seen:
                            continue
                        if not _applies(rule, item.path):
                            continue
                        if not _COMPILED[(pack.id, rule.id)].search(line.text):
                            continue
                        seen.add(key)
                        if hits >= pack.max_per_review:
                            capped = True
                            continue
                        hits += 1
                        findings.append(
                            CheckFinding(
                                path=item.path,
                                line_number=line.new_no,
                                comment=_comment(pack, rule),
                                pack=pack.id,
                                rule=rule.id,
                            )
                        )
        if capped and warnings is not None:
            warnings.append(
                f"The {pack.id} check found more than {pack.max_per_review} issue(s); "
                "the rest were not reported."
            )
    return findings


def counts(findings: list[CheckFinding]) -> dict[str, int]:
    """`{pack_id: n}`, registry order, only packs with a hit."""
    result: dict[str, int] = {}
    for pack in PACKS:
        total = sum(1 for finding in findings if finding.pack == pack.id)
        if total:
            result[pack.id] = total
    return result


def describe(totals: dict[str, int]) -> str:
    """`2 secrets, 1 hygiene` — the phrase shared by the note and the progress row."""
    return ", ".join(f"{count} {pack_id}" for pack_id, count in totals.items())
