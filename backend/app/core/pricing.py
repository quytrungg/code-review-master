"""Estimated model prices, USD per 1,000,000 tokens.

Every dollar figure the product shows is derived from this table and is an **estimate**: it is a
published list price, not a provider invoice. A model that is not listed here has no price, and the
ledger stores `NULL` rather than a guess — "unknown" is honest, "free" is not.

Two kinds of row live here:

- The first-party APIs (Claude, OpenAI) the bundled fallback lists offer.
- The hosted Ollama Cloud catalogue. Since 2026-08-31 Ollama bills cloud usage per token
  (pay-as-you-go credits, or the credits included with Pro/Max/Team), so a cloud call has a real
  dollar cost. Re-check `https://ollama.com/pricing` when adding a model.

Rates are the **standard** tier. Ollama publishes a cached-input rate and a half-price off-peak
window (outside 12:00–18:00 UTC on weekdays, all weekend); `llm_calls` records neither cached tokens
nor the tier, so an estimate here is an upper bound, never a discount. `clef` is left out on purpose:
it publishes an input rate and no output rate, which this shape cannot express.

Keep the table current rather than complete: a stale price is worse than a missing one because it
looks exact.
"""

from __future__ import annotations

from typing import TypedDict


class ModelPrice(TypedDict):
    input: float
    output: float


MODEL_PRICES: dict[str, ModelPrice] = {
    # --- Anthropic ---------------------------------------------------------------------------
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.00},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    # --- OpenAI ------------------------------------------------------------------------------
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    # --- Ollama Cloud (checked 2026-11-10) ----------------------------------------------------
    "beam": {"input": 0.125, "output": 0.40},
    "deepseek-v4.1-flash": {"input": 0.30, "output": 1.20},
    "deepseek-v4-pro": {"input": 1.32, "output": 3.96},
    "gemma4": {"input": 0.14, "output": 0.40},
    "glm-5.3-flash": {"input": 0.15, "output": 0.50},
    "glm-5.2": {"input": 1.40, "output": 4.40},
    "glm-5.3": {"input": 1.40, "output": 4.40},
    "gpt-oss:120b": {"input": 0.15, "output": 0.60},
    "gpt-oss:20b": {"input": 0.07, "output": 0.30},
    "kimi-k2.6": {"input": 0.95, "output": 4.00},
    "kimi-k2.7-code": {"input": 0.95, "output": 4.00},
    "kimi-k3.1-pro": {"input": 2.00, "output": 10.00},
    "kimi-k3": {"input": 3.00, "output": 15.00},
    "mimo-v2.6-flash": {"input": 0.14, "output": 0.28},
    "mimo-v2.6-pro": {"input": 0.435, "output": 0.87},
    "minimax-m3.1-flash": {"input": 0.15, "output": 0.60},
    "minimax-m3": {"input": 0.60, "output": 2.40},
    "mistral-large-4": {"input": 0.70, "output": 2.10},
    "muse-spark-open": {"input": 1.25, "output": 4.25},
    "nemotron-3-super": {"input": 0.015, "output": 0.60},
    "nemotron-3-ultra": {"input": 0.10, "output": 3.00},
}

# A local daemon runs on the operator's own hardware: there is no per-token bill to estimate.
# Ollama **Cloud** is not in here — it is metered and priced from the table above.
FREE_PROVIDERS = ("ollama-local",)

# Longest prefix first: `deepseek-v4.1-flash` must win over `deepseek-v4-pro`, `gpt-4o-mini` over
# `gpt-4o`, and `glm-5.3-flash` over `glm-5.3`.
_PREFIXES = sorted(MODEL_PRICES, key=len, reverse=True)


def price_for(model: str) -> ModelPrice | None:
    """Published rate for a model name, matched by prefix (`claude-3-haiku-20240307` matches)."""
    name = (model or "").strip().lower()
    if not name:
        return None
    for prefix in _PREFIXES:
        if name.startswith(prefix):
            return MODEL_PRICES[prefix]
    return None


def estimate_cost(
    provider: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float | None:
    """Estimated USD for one call, or `None` when the model or the counts are unknown.

    Never raises: telemetry is advisory, so an unrecognised model simply has no cost.
    """
    if prompt_tokens is None or completion_tokens is None:
        return None
    if provider in FREE_PROVIDERS:
        return 0.0
    price = price_for(model)
    if price is None:
        return None
    cost = prompt_tokens / 1_000_000 * price["input"] + completion_tokens / 1_000_000 * price["output"]
    return round(cost, 6)
