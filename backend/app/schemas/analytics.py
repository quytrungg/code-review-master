"""Response models for the analytics endpoint. Every dollar figure is an estimate."""

from __future__ import annotations

from pydantic import BaseModel


class AnalyticsTotals(BaseModel):
    calls: int = 0
    failed_calls: int = 0
    # Calls whose model had a price; the denominator behind every dollar figure.
    priced_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None


class AnalyticsLatency(BaseModel):
    median_ms: int | None = None
    p95_ms: int | None = None
    avg_ms: int | None = None


class ProviderUsage(BaseModel):
    provider: str
    calls: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None


class ModelUsage(BaseModel):
    """One row of the comparison table: what a model cost and how its findings were received."""

    provider: str
    # Full model id, `<provider>:<name>`, the same form as `code_reviews.model_used`.
    model: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None
    avg_latency_ms: int | None = None
    findings: int = 0
    accepted: int = 0
    acceptance_rate: float | None = None
    pushed_back: int = 0
    pushback_rate: float | None = None


class PurposeUsage(BaseModel):
    purpose: str
    calls: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None


class QualitySummary(BaseModel):
    findings: int = 0
    accepted: int = 0
    acceptance_rate: float | None = None
    pushed_back: int = 0
    pushback_rate: float | None = None


class BudgetStatus(BaseModel):
    """Current calendar month against the soft caps. `level` never blocks anything."""

    month: str
    token_budget: int | None = None
    dollar_budget: float | None = None
    tokens_used: int = 0
    dollars_used: float | None = None
    token_pct: float | None = None
    dollar_pct: float | None = None
    level: str = "ok"  # ok | warn | over


class AnalyticsRead(BaseModel):
    window_days: int
    generated_at: str | None = None
    totals: AnalyticsTotals
    latency: AnalyticsLatency
    by_provider: list[ProviderUsage]
    by_model: list[ModelUsage]
    by_purpose: list[PurposeUsage]
    quality: QualitySummary
    budget: BudgetStatus
