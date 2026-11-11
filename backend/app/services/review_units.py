"""Split a diff that would be truncated into review parts.

One model call over one diff is capped at `diff_max_chars`; past that the tail used to be cut off
and silently unreviewed. `plan_units` turns the changed files into as few parts as the budget
allows, packing whole files in diff order and never splitting one — a part is a list of files, so
every finding still anchors against the full parsed diff afterwards.

Splitting is triggered by the *ceiling*, not by the part size: a diff that fits in `diff_max_chars`
is one call, exactly as before, even when it is larger than `review_unit_chars`. Parts exist to
remove a cut, not to shrink a call that was already complete.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.diff_parser import FileDiff
from app.services.prompts import file_block_size


@dataclass(frozen=True)
class ReviewUnit:
    """One model call's worth of files."""

    index: int  # 1-based, for "part 2 of 4"
    total: int
    files: list[FileDiff]
    budget: int  # rendered characters this part's prompt may use
    oversized: bool = False  # a single file too large for a normal part

    @property
    def paths(self) -> list[str]:
        return [item.path for item in self.files]


def plan_units(
    files: list[FileDiff], unit_chars: int, max_chars: int
) -> list[ReviewUnit]:
    """Pack `files` into parts: one part when the diff fits, otherwise parts of ≤ `unit_chars`."""
    if not files:
        return []

    sized = [(item, file_block_size(item)) for item in files]
    if sum(size for _, size in sized) <= max_chars:
        return [ReviewUnit(index=1, total=1, files=list(files), budget=max_chars)]

    unit_chars = max(unit_chars, 1)
    groups: list[tuple[list[FileDiff], bool]] = []
    current: list[FileDiff] = []
    used = 0
    for item, size in sized:
        if size > unit_chars:
            # Nothing else can share a part with it: give it its own and let it truncate.
            if current:
                groups.append((current, False))
                current, used = [], 0
            groups.append(([item], True))
            continue
        if current and used + size > unit_chars:
            groups.append((current, False))
            current, used = [], 0
        current.append(item)
        used += size
    if current:
        groups.append((current, False))

    total = len(groups)
    return [
        ReviewUnit(index=index, total=total, files=group, budget=unit_chars, oversized=oversized)
        for index, (group, oversized) in enumerate(groups, start=1)
    ]
