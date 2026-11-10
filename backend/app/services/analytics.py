"""Aggregates behind `GET /api/analytics`: spend, volume, latency and review quality.

Every figure is per account — the ledger has no `user_id`, so each query joins
`llm_calls → code_reviews` and filters on the owner. Money is *estimated* from `core/pricing`;
a model with no price contributes tokens but no dollars, and a window with nothing priced reports
`None` rather than `$0.00`.

Counting, summing and averaging happen in SQL. Percentiles are a nearest-rank index into the sorted
latency column: PostgreSQL has `percentile_cont`, SQLite does not, and the window is one integer
column wide, so the sorted-index answer is the same on both and much simpler than a dialect switch.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.llm_call import LLMCall, LLMPurpose
from app.models.review import (
    CodeReview,
    MessageRole,
    ReviewThread,
    RoundStatus,
    ThreadMessage,
    ThreadOrigin,
    ThreadRound,
)
from app.models.settings import Settings
from app.schemas.analytics import (
    AnalyticsLatency,
    AnalyticsRead,
    AnalyticsTotals,
    BudgetStatus,
    ModelUsage,
    ProviderUsage,
    PurposeUsage,
    QualitySummary,
)
from app.schemas.review import ReviewUsage

BUDGET_WARN_PCT = 80.0
BUDGET_OVER_PCT = 100.0


def _percentile(values: list[int], pct: float) -> int | None:
    """Nearest-rank percentile: the smallest sample at or above `pct` percent of the data."""
    if not values:
        return None
    rank = max(1, math.ceil(pct / 100 * len(values)))
    return values[min(rank, len(values)) - 1]


def _rate(part: int, total: int) -> float | None:
    return round(part / total * 100, 1) if total else None


def _money(value: float | None, priced: int) -> float | None:
    """A dollar total, or `None` when nothing in the group had a price."""
    return round(value, 6) if value is not None and priced else None


def _model_key(model_used: str | None) -> str:
    """`<provider>:<name>`, normalising the legacy `ollama:` prefix (now the hosted API)."""
    prefix, _, name = (model_used or "").partition(":")
    if not name:
        return model_used or "unknown"
    return f"{'ollama-cloud' if prefix == 'ollama' else prefix}:{name}"


def _split_key(key: str) -> tuple[str, str]:
    provider, _, name = key.partition(":")
    return (provider or "unknown"), (name or key)


def _call_rows(db: Session, user_id: int, since: datetime):
    """Calls in the window, grouped by provider, model and purpose, with their totals."""
    return db.execute(
        select(
            LLMCall.provider,
            LLMCall.model,
            LLMCall.purpose,
            func.count().label("calls"),
            func.sum(case((LLMCall.ok.is_(False), 1), else_=0)).label("failed_calls"),
            func.coalesce(func.sum(LLMCall.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(LLMCall.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(LLMCall.latency_ms), 0).label("latency_sum"),
            func.sum(LLMCall.estimated_cost_usd).label("cost"),
            func.sum(case((LLMCall.estimated_cost_usd.is_not(None), 1), else_=0)).label("priced"),
        )
        .join(CodeReview, LLMCall.review_id == CodeReview.id)
        .where(CodeReview.user_id == user_id, LLMCall.created_at >= since)
        .group_by(LLMCall.provider, LLMCall.model, LLMCall.purpose)
    ).all()


def _quality_by_model(
    db: Session, user_id: int, since: datetime
) -> dict[str, dict[str, int]]:
    """Per model id: findings analysed, accepted and pushed back, for AI-authored threads."""
    threads = db.execute(
        select(ReviewThread.id, CodeReview.model_used)
        .join(CodeReview, ReviewThread.review_id == CodeReview.id)
        .where(
            CodeReview.user_id == user_id,
            ReviewThread.origin == ThreadOrigin.AI_GENERATED,
            ReviewThread.created_at >= since,
        )
    ).all()
    if not threads:
        return {}

    # The latest round decides acceptance: a finding re-opened for discussion is not published yet.
    latest: dict[int, tuple[int, str]] = {}
    for thread_id, round_number, status in db.execute(
        select(ThreadRound.thread_id, ThreadRound.round_number, ThreadRound.status)
        .join(ReviewThread, ThreadRound.thread_id == ReviewThread.id)
        .join(CodeReview, ReviewThread.review_id == CodeReview.id)
        .where(
            CodeReview.user_id == user_id,
            ReviewThread.origin == ThreadOrigin.AI_GENERATED,
            ReviewThread.created_at >= since,
        )
    ):
        current = latest.get(thread_id)
        if current is None or round_number >= current[0]:
            latest[thread_id] = (round_number, status)

    # Push-back is the reviewer engaging: they typed a reply, or explicitly discarded the round.
    engaged = set(
        db.scalars(
            select(ThreadMessage.thread_id)
            .join(ReviewThread, ThreadMessage.thread_id == ReviewThread.id)
            .join(CodeReview, ReviewThread.review_id == CodeReview.id)
            .where(
                CodeReview.user_id == user_id,
                ReviewThread.origin == ThreadOrigin.AI_GENERATED,
                ReviewThread.created_at >= since,
                ThreadMessage.role == MessageRole.USER,
            )
            .distinct()
        )
    )

    buckets: dict[str, dict[str, int]] = {}
    for thread_id, model_used in threads:
        bucket = buckets.setdefault(
            _model_key(model_used), {"findings": 0, "accepted": 0, "pushed_back": 0}
        )
        status = latest.get(thread_id, (0, None))[1]
        bucket["findings"] += 1
        bucket["accepted"] += int(status == RoundStatus.PUBLISHED)
        bucket["pushed_back"] += int(thread_id in engaged or status == RoundStatus.RESOLVED_NO_REPLY)
    return buckets


def _budget(db: Session, user_id: int, now: datetime) -> BudgetStatus:
    """This calendar month against the soft caps; `days` deliberately does not apply here."""
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    calls, tokens, cost, priced = db.execute(
        select(
            func.count(),
            func.coalesce(
                func.sum(
                    func.coalesce(LLMCall.prompt_tokens, 0)
                    + func.coalesce(LLMCall.completion_tokens, 0)
                ),
                0,
            ),
            func.sum(LLMCall.estimated_cost_usd),
            func.sum(case((LLMCall.estimated_cost_usd.is_not(None), 1), else_=0)),
        )
        .join(CodeReview, LLMCall.review_id == CodeReview.id)
        .where(CodeReview.user_id == user_id, LLMCall.created_at >= month_start)
    ).one()

    row = db.scalars(select(Settings).where(Settings.user_id == user_id)).first()
    token_budget = getattr(row, "monthly_token_budget", None)
    dollar_budget = getattr(row, "monthly_dollar_budget", None)

    dollars_used = _money(cost, priced)
    token_pct = round(tokens / token_budget * 100, 1) if token_budget else None
    dollar_pct = (
        round(dollars_used / dollar_budget * 100, 1)
        if dollar_budget and dollars_used is not None
        else None
    )
    measured = [pct for pct in (token_pct, dollar_pct) if pct is not None]
    level = "ok"
    if any(pct >= BUDGET_OVER_PCT for pct in measured):
        level = "over"
    elif any(pct >= BUDGET_WARN_PCT for pct in measured):
        level = "warn"

    return BudgetStatus(
        month=month_start.strftime("%Y-%m"),
        token_budget=token_budget,
        dollar_budget=dollar_budget,
        tokens_used=int(tokens or 0),
        dollars_used=dollars_used,
        token_pct=token_pct,
        dollar_pct=dollar_pct,
        level=level,
    )


def summarise(db: Session, user_id: int, days: int) -> AnalyticsRead:
    """The whole analytics payload for one account over the last `days` days."""
    now = utcnow()
    since = now - timedelta(days=days)

    totals = {"calls": 0, "failed": 0, "prompt": 0, "completion": 0, "latency": 0, "priced": 0}
    cost_total: float | None = None
    providers: dict[str, dict] = {}
    models: dict[str, dict] = {}
    purposes: dict[str, dict] = {}

    for row in _call_rows(db, user_id, since):
        calls = int(row.calls or 0)
        prompt = int(row.prompt_tokens or 0)
        completion = int(row.completion_tokens or 0)
        latency = int(row.latency_sum or 0)
        priced = int(row.priced or 0)

        totals["calls"] += calls
        totals["failed"] += int(row.failed_calls or 0)
        totals["prompt"] += prompt
        totals["completion"] += completion
        totals["latency"] += latency
        totals["priced"] += priced
        if row.cost is not None:
            cost_total = (cost_total or 0.0) + row.cost

        provider = providers.setdefault(row.provider, {"calls": 0, "tokens": 0, "cost": None, "priced": 0})
        provider["calls"] += calls
        provider["tokens"] += prompt + completion
        provider["priced"] += priced
        if row.cost is not None:
            provider["cost"] = (provider["cost"] or 0.0) + row.cost

        model_id = f"{row.provider}:{row.model}"
        model = models.setdefault(
            model_id,
            {
                "provider": row.provider,
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "latency": 0,
                "cost": None,
                "priced": 0,
            },
        )
        model["calls"] += calls
        model["prompt_tokens"] += prompt
        model["completion_tokens"] += completion
        model["latency"] += latency
        model["priced"] += priced
        if row.cost is not None:
            model["cost"] = (model["cost"] or 0.0) + row.cost

        purpose = purposes.setdefault(row.purpose, {"calls": 0, "tokens": 0, "cost": None, "priced": 0})
        purpose["calls"] += calls
        purpose["tokens"] += prompt + completion
        purpose["priced"] += priced
        if row.cost is not None:
            purpose["cost"] = (purpose["cost"] or 0.0) + row.cost

    latencies = sorted(
        db.scalars(
            select(LLMCall.latency_ms)
            .join(CodeReview, LLMCall.review_id == CodeReview.id)
            .where(CodeReview.user_id == user_id, LLMCall.created_at >= since)
        )
    )
    avg_ms = round(sum(latencies) / len(latencies)) if latencies else None

    quality = _quality_by_model(db, user_id, since)
    model_rows: list[ModelUsage] = []
    for model_id, bucket in quality.items():
        entry = models.setdefault(
            model_id,
            {
                "provider": _split_key(model_id)[0],
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "latency": 0,
                "cost": None,
                "priced": 0,
            },
        )
        entry["quality"] = bucket

    total_accepted = sum(bucket["accepted"] for bucket in quality.values())
    total_pushed = sum(bucket["pushed_back"] for bucket in quality.values())
    total_findings = sum(bucket["findings"] for bucket in quality.values())

    for model_id, entry in models.items():
        bucket = entry.pop("quality", {"findings": 0, "accepted": 0, "pushed_back": 0})
        calls = int(entry["calls"])
        prompt = int(entry["prompt_tokens"])
        completion = int(entry["completion_tokens"])
        model_rows.append(
            ModelUsage(
                provider=entry["provider"],
                model=model_id,
                calls=calls,
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=prompt + completion,
                estimated_cost_usd=_money(entry["cost"], entry["priced"]),
                avg_latency_ms=round(entry["latency"] / calls) if calls else None,
                findings=bucket["findings"],
                accepted=bucket["accepted"],
                acceptance_rate=_rate(bucket["accepted"], bucket["findings"]),
                pushed_back=bucket["pushed_back"],
                pushback_rate=_rate(bucket["pushed_back"], bucket["findings"]),
            )
        )
    model_rows.sort(key=lambda item: (-item.calls, item.model))

    purpose_rows = [
        PurposeUsage(
            purpose=name,
            calls=int(purposes.get(name, {}).get("calls", 0)),
            total_tokens=int(purposes.get(name, {}).get("tokens", 0)),
            estimated_cost_usd=_money(
                purposes.get(name, {}).get("cost"), purposes.get(name, {}).get("priced", 0)
            ),
        )
        for name in LLMPurpose.ALL
    ]

    return AnalyticsRead(
        window_days=days,
        generated_at=now.isoformat().replace("+00:00", "Z"),
        totals=AnalyticsTotals(
            calls=totals["calls"],
            failed_calls=totals["failed"],
            priced_calls=totals["priced"],
            prompt_tokens=int(totals["prompt"]),
            completion_tokens=int(totals["completion"]),
            total_tokens=int(totals["prompt"] + totals["completion"]),
            estimated_cost_usd=_money(cost_total, totals["priced"]),
        ),
        latency=AnalyticsLatency(
            median_ms=_percentile(latencies, 50),
            p95_ms=_percentile(latencies, 95),
            avg_ms=avg_ms,
        ),
        by_provider=[
            ProviderUsage(
                provider=name,
                calls=entry["calls"],
                total_tokens=entry["tokens"],
                estimated_cost_usd=_money(entry["cost"], entry["priced"]),
            )
            for name, entry in sorted(providers.items(), key=lambda pair: -pair[1]["calls"])
        ],
        by_model=model_rows,
        by_purpose=purpose_rows,
        quality=QualitySummary(
            findings=total_findings,
            accepted=total_accepted,
            acceptance_rate=_rate(total_accepted, total_findings),
            pushed_back=total_pushed,
            pushback_rate=_rate(total_pushed, total_findings),
        ),
        budget=_budget(db, user_id, now),
    )


def review_usage(db: Session, review_id: int) -> ReviewUsage:
    """The header line for one review: calls, tokens, estimated cost and total latency."""
    calls, prompt, completion, latency, cost = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(LLMCall.prompt_tokens), 0),
            func.coalesce(func.sum(LLMCall.completion_tokens), 0),
            func.coalesce(func.sum(LLMCall.latency_ms), 0),
            func.sum(LLMCall.estimated_cost_usd),
        ).where(LLMCall.review_id == review_id)
    ).one()
    return ReviewUsage(
        calls=int(calls or 0),
        prompt_tokens=int(prompt or 0),
        completion_tokens=int(completion or 0),
        total_tokens=int((prompt or 0) + (completion or 0)),
        # Sum of the priced calls; `None` when none of them had a price at all.
        estimated_cost_usd=round(cost, 6) if cost is not None else None,
        latency_ms=int(latency or 0),
    )
