"""LatencyBudget — per-action latency budget with regression detection.

Tracks p50/p95/p99 for each action type and flags budget violations.
Wire into DesktopAgent._execute_single_action() after adapter call.

Budgets are in milliseconds and based on expected real-world latencies
for desktop interactions (not network-bound browser actions).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass

# Budgets in milliseconds — based on expected real-world latencies
ACTION_BUDGETS: dict[str, dict[str, float]] = {
    "click":      {"p50": 50,   "p95": 200,   "p99": 500},
    "fill":       {"p50": 100,  "p95": 300,   "p99": 800},
    "type_text":  {"p50": 200,  "p95": 500,   "p99": 1000},
    "key_press":  {"p50": 20,   "p95": 100,   "p99": 200},
    "scroll":     {"p50": 30,   "p95": 100,   "p99": 300},
    "screenshot": {"p50": 100,  "p95": 500,   "p99": 1000},
    "snapshot":   {"p50": 100,  "p95": 300,   "p99": 800},
    "navigate":   {"p50": 500,  "p95": 2000,  "p99": 5000},
    "automate":   {"p50": 2000, "p95": 10000, "p99": 30000},
    "default":    {"p50": 200,  "p95": 500,   "p99": 1000},
}


@dataclass
class LatencyMeasurement:
    """A single latency measurement for an action."""

    action: str
    duration_ms: float
    timestamp: float
    budget_p95: float
    budget_p99: float
    exceeded_p95: bool
    exceeded_p99: bool

    @property
    def exceeded(self) -> bool:
        """True if the measurement exceeded the p95 budget."""
        return self.exceeded_p95


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Compute a percentile from a sorted list of values."""
    if not sorted_values:
        return 0.0
    idx = max(0, min(int(len(sorted_values) * pct / 100.0), len(sorted_values) - 1))
    return sorted_values[idx]


class LatencyBudget:
    """Per-action latency budget with measurement and regression detection.

    Records durations for each action type and computes p50/p95/p99.
    Individual measurements are checked against configured budgets.
    """

    def __init__(self, budgets: dict[str, dict[str, float]] | None = None) -> None:
        self._budgets = budgets or ACTION_BUDGETS
        self._measurements: dict[str, list[float]] = defaultdict(list)
        self._violations: list[LatencyMeasurement] = []
        self._lock = threading.Lock()

    def _get_budget(self, action: str) -> dict[str, float]:
        """Get budget for an action, falling back to default."""
        return self._budgets.get(action, self._budgets.get("default", ACTION_BUDGETS["default"]))

    def record(self, action: str, duration_ms: float) -> LatencyMeasurement:
        """Record a latency measurement.

        Returns the measurement object with budget violation flags.
        """
        budget = self._get_budget(action)
        exceeded_p95 = duration_ms > budget["p95"]
        exceeded_p99 = duration_ms > budget["p99"]

        measurement = LatencyMeasurement(
            action=action,
            duration_ms=duration_ms,
            timestamp=time.monotonic(),
            budget_p95=budget["p95"],
            budget_p99=budget["p99"],
            exceeded_p95=exceeded_p95,
            exceeded_p99=exceeded_p99,
        )

        with self._lock:
            self._measurements[action].append(duration_ms)
            if exceeded_p95:
                self._violations.append(measurement)

        return measurement

    def check(self, action: str, duration_ms: float) -> bool:
        """Check if a duration is within the p95 budget.

        Returns True if within budget, False if violated.
        Does NOT record the measurement.
        """
        budget = self._get_budget(action)
        return duration_ms <= budget["p95"]

    @property
    def summary(self) -> dict[str, dict[str, float]]:
        """Per-action latency summary with p50/p95/p99.

        Only includes actions that have measurements.
        """
        with self._lock:
            result: dict[str, dict[str, float]] = {}
            for action, durations in self._measurements.items():
                sorted_d = sorted(durations)
                result[action] = {
                    "count": len(sorted_d),
                    "p50": _percentile(sorted_d, 50),
                    "p95": _percentile(sorted_d, 95),
                    "p99": _percentile(sorted_d, 99),
                    "min": sorted_d[0] if sorted_d else 0.0,
                    "max": sorted_d[-1] if sorted_d else 0.0,
                }
            return result

    @property
    def violations(self) -> list[LatencyMeasurement]:
        """All recorded budget violations (p95 exceeded)."""
        with self._lock:
            return list(self._violations)

    def reset(self) -> None:
        """Clear all measurements and violations."""
        with self._lock:
            self._measurements.clear()
            self._violations.clear()
