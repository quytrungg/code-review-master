#!/usr/bin/env python
"""Recompute `llm_calls.estimated_cost_usd` from the stored tokens and the current price table.

One-off data repair for rows the price table did not cover when they were written: their cost is
stored as `0.0` or `NULL`, and only a recompute can fix that, because the price table is not
consulted again after the row is written. Two runs are recorded in the plans — phase 24 (cloud calls
stored as `0.0` while Ollama Cloud was treated as free) and phase 58 (Claude calls stored as `NULL`
before the table gained family rows).

    python scripts/backfill_llm_costs.py            # dry run: report only, writes nothing
    python scripts/backfill_llm_costs.py --apply    # write the corrected values

`--dry-run` is the default on purpose: this rewrites money on rows the operator already has. The
computation is deterministic and idempotent, so re-running `--apply` changes nothing.

Rows are only touched when the recomputed value differs: a call whose model still has no published
price (`estimate_cost` returns `None`) keeps whatever it has, and a failed call with no tokens is
left alone. A `NULL` row that recomputes to `0.0` (a free local call) is written as `0.0` — known
free is not the same as unknown. This is a repair, not an Alembic revision, so `alembic_version`
stays at head.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.pricing import estimate_cost  # noqa: E402
from app.models.llm_call import LLMCall  # noqa: E402

PRECISION = 6


@dataclass
class Group:
    """Report row for one provider/model pair."""

    provider: str
    model: str
    rows: int = 0
    changed: int = 0
    old_total: float = 0.0
    new_total: float = 0.0
    unpriced: int = 0


@dataclass
class Result:
    groups: dict[tuple[str, str], Group] = field(default_factory=dict)

    @property
    def rows(self) -> int:
        return sum(group.rows for group in self.groups.values())

    @property
    def changed(self) -> int:
        return sum(group.changed for group in self.groups.values())

    @property
    def old_total(self) -> float:
        return sum(group.old_total for group in self.groups.values())

    @property
    def new_total(self) -> float:
        return sum(group.new_total for group in self.groups.values())

    def sorted_groups(self) -> list[Group]:
        return sorted(self.groups.values(), key=lambda group: (group.provider, group.model))


def recompute(db: Session, *, apply: bool = False) -> Result:
    """Reprice every ledger row from its own tokens. `apply=False` leaves the rows untouched."""
    result = Result()
    for row in db.scalars(select(LLMCall).order_by(LLMCall.id)):
        group = result.groups.setdefault(
            (row.provider, row.model), Group(provider=row.provider, model=row.model)
        )
        group.rows += 1
        group.old_total += row.estimated_cost_usd or 0.0

        cost = estimate_cost(row.provider, row.model, row.prompt_tokens, row.completion_tokens)
        if cost is None:
            group.unpriced += 1
            group.new_total += row.estimated_cost_usd or 0.0
            continue

        group.new_total += cost
        # Compare by identity, not `or 0.0`: a NULL row that recomputes to 0.0 (a free local call)
        # must be written too, or it stays "unknown" forever.
        if (
            row.estimated_cost_usd is not None
            and abs(cost - row.estimated_cost_usd) < 10**-PRECISION
        ):
            continue
        group.changed += 1
        if apply:
            row.estimated_cost_usd = cost

    if apply:
        db.commit()
    else:
        db.rollback()
    return result


def _report(result: Result) -> str:
    lines = [
        f"{'provider':<14} {'model':<30} {'rows':>5} {'changed':>8} "
        f"{'old $':>12} {'new $':>12} {'unpriced':>9}"
    ]
    for group in result.sorted_groups():
        lines.append(
            f"{group.provider:<14} {group.model[:30]:<30} {group.rows:>5} {group.changed:>8} "
            f"{group.old_total:>12.6f} {group.new_total:>12.6f} {group.unpriced:>9}"
        )
    lines.append(
        f"{'TOTAL':<14} {'':<30} {result.rows:>5} {result.changed:>8} "
        f"{result.old_total:>12.6f} {result.new_total:>12.6f}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Recompute estimated LLM costs from the stored tokens (one-off repair).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python scripts/backfill_llm_costs.py\n"
            "  python scripts/backfill_llm_costs.py --apply\n"
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the corrected values. Without it the run only reports.",
    )
    args = parser.parse_args(argv)

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        result = recompute(db, apply=args.apply)
        print(_report(result))

    if not args.apply:
        print("dry run: nothing written (re-run with --apply to update these rows)")
    else:
        print(f"applied: {result.changed} row(s) updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
