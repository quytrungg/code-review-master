from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import pytest
from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

import backfill_llm_costs as backfill  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.llm_call import LLMCall  # noqa: E402


@pytest.fixture()
def calls():
    """Insert ledger rows and delete exactly those again — the temp DB is shared per test."""
    ids: list[int] = []

    def make(**kwargs) -> int:
        with SessionLocal() as db:
            row = LLMCall(purpose="ingest", latency_ms=10, **kwargs)
            db.add(row)
            db.commit()
            ids.append(row.id)
            return row.id

    yield make

    with SessionLocal() as db:
        for row in db.scalars(select(LLMCall).where(LLMCall.id.in_(ids))):
            db.delete(row)
        db.commit()


def stored(row_id: int) -> float | None:
    with SessionLocal() as db:
        row = db.get(LLMCall, row_id)
        assert row is not None
        return row.estimated_cost_usd


def test_dry_run_prices_a_zeroed_cloud_call_but_writes_nothing(calls: Callable) -> None:
    row_id = calls(
        provider="ollama-cloud",
        model="deepseek-v4.1-flash:1017",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
        total_tokens=2_000_000,
        estimated_cost_usd=0.0,
    )

    with SessionLocal() as db:
        result = backfill.recompute(db, apply=False)

    group = result.groups[("ollama-cloud", "deepseek-v4.1-flash:1017")]
    assert group.changed == 1
    assert group.old_total == 0.0
    assert group.new_total == pytest.approx(1.5)
    assert stored(row_id) == 0.0


def test_apply_reprices_the_row_and_a_second_run_changes_nothing(calls: Callable) -> None:
    row_id = calls(
        provider="ollama-cloud",
        model="deepseek-v4.1-flash:1017",
        prompt_tokens=704_959,
        completion_tokens=95_885,
        total_tokens=800_844,
        estimated_cost_usd=0.0,
    )

    with SessionLocal() as db:
        first = backfill.recompute(db, apply=True)
    assert first.changed == 1
    assert stored(row_id) == pytest.approx(0.326550, abs=1e-6)

    with SessionLocal() as db:
        second = backfill.recompute(db, apply=True)
    assert second.changed == 0
    assert stored(row_id) == pytest.approx(0.326550, abs=1e-6)


def test_a_model_without_a_published_price_keeps_its_value(calls: Callable) -> None:
    row_id = calls(
        provider="ollama-cloud",
        model="some-unlisted-model",
        prompt_tokens=1000,
        completion_tokens=500,
        total_tokens=1500,
        estimated_cost_usd=0.004,
    )

    with SessionLocal() as db:
        result = backfill.recompute(db, apply=True)

    group = result.groups[("ollama-cloud", "some-unlisted-model")]
    assert group.changed == 0
    assert group.unpriced == 1
    assert stored(row_id) == 0.004


def test_a_failed_call_without_tokens_stays_unknown(calls: Callable) -> None:
    row_id = calls(
        provider="ollama-local",
        model="llama3",
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        estimated_cost_usd=None,
        ok=False,
    )

    with SessionLocal() as db:
        result = backfill.recompute(db, apply=True)

    group = result.groups[("ollama-local", "llama3")]
    assert group.changed == 0
    assert group.unpriced == 1
    assert stored(row_id) is None
