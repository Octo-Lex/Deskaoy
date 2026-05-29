"""CostTracker — LLM token usage tracking with cost estimation.

Aggregates token usage per provider/model and estimates USD cost.
Enforces a budget cap — when exceeded, automate calls return
BUDGET_EXHAUSTED status.

Wire into SimpleLLMClient._chat() and DesktopAgent._execute_automate().
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

# Cost per 1M tokens (USD) — approximate, per-provider per-model
PRICING: dict[str, dict[str, dict[str, float]]] = {
    "openai": {
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    },
    "anthropic": {
        "claude-haiku-4-20250414": {"input": 0.80, "output": 4.00},
        "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    },
}

# Default pricing for unknown models (per 1M tokens)
DEFAULT_PRICING: dict[str, float] = {"input": 1.00, "output": 5.00}


@dataclass
class CostEntry:
    """A single LLM call cost record."""

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    timestamp: float


class CostTracker:
    """LLM cost tracking with budget enforcement.

    Records each LLM call's token usage and estimated cost.
    Tracks total spend against a configurable budget.
    """

    def __init__(self, budget_usd: float = 1.0) -> None:
        self._budget_usd = budget_usd
        self._entries: list[CostEntry] = []
        self._lock = threading.Lock()

    def _estimate_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Estimate USD cost for a single LLM call."""
        provider_pricing = PRICING.get(provider, {})
        model_pricing = provider_pricing.get(model, DEFAULT_PRICING)
        input_cost = (input_tokens / 1_000_000) * model_pricing.get("input", DEFAULT_PRICING["input"])
        output_cost = (output_tokens / 1_000_000) * model_pricing.get("output", DEFAULT_PRICING["output"])
        return input_cost + output_cost

    def record(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float = 0.0,
    ) -> CostEntry:
        """Record an LLM call and return the cost entry.

        Calculates estimated cost based on provider/model pricing.
        """
        cost = self._estimate_cost(provider, model, input_tokens, output_tokens)

        entry = CostEntry(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            timestamp=time.monotonic(),
        )

        with self._lock:
            self._entries.append(entry)

        return entry

    @property
    def total_cost(self) -> float:
        """Total estimated cost across all recorded calls."""
        with self._lock:
            return sum(e.cost_usd for e in self._entries)

    def _total_cost_unlocked(self) -> float:
        """Total cost without acquiring the lock (caller must hold it)."""
        return sum(e.cost_usd for e in self._entries)

    @property
    def total_tokens(self) -> int:
        """Total tokens consumed across all calls."""
        with self._lock:
            return sum(e.input_tokens + e.output_tokens for e in self._entries)

    @property
    def budget_remaining(self) -> float:
        """Remaining budget in USD."""
        return max(0.0, self._budget_usd - self.total_cost)

    @property
    def budget_exceeded(self) -> bool:
        """True if total cost has exceeded the budget."""
        return self.total_cost >= self._budget_usd

    @property
    def budget_usd(self) -> float:
        """The configured budget limit."""
        return self._budget_usd

    @property
    def summary(self) -> dict:
        """Summary of cost tracking state."""
        with self._lock:
            total = self._total_cost_unlocked()
            by_provider: dict[str, dict] = {}
            for e in self._entries:
                key = f"{e.provider}/{e.model}"
                if key not in by_provider:
                    by_provider[key] = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
                by_provider[key]["calls"] += 1
                by_provider[key]["input_tokens"] += e.input_tokens
                by_provider[key]["output_tokens"] += e.output_tokens
                by_provider[key]["cost_usd"] += e.cost_usd

            return {
                "total_cost_usd": total,
                "total_tokens": sum(e.input_tokens + e.output_tokens for e in self._entries),
                "budget_usd": self._budget_usd,
                "budget_remaining_usd": max(0.0, self._budget_usd - total),
                "budget_exceeded": total >= self._budget_usd,
                "total_calls": len(self._entries),
                "by_provider_model": by_provider,
            }

    def reset(self) -> None:
        """Clear all recorded entries."""
        with self._lock:
            self._entries.clear()
