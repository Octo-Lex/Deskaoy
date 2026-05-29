"""Session Budget — session-level resource tracking with escalation.

Tracks cumulative actions, costs, and duration within a session.
Enforces hard limits (max_actions, max_denials, max_cost, max_duration)
and triggers escalation when soft thresholds are crossed.

Pattern source: deterministic-agent-control-protocol (det-acp) session.ts
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class SessionLimits:
    """Hard and soft limits for a session."""
    max_actions: int = 100              # Max total actions per session
    max_denials: int = 10               # Max denials before auto-terminate
    max_cost_usd: float = 1.0           # Max cumulative cost (USD)
    max_duration_ms: float = 1_800_000  # 30 minutes
    escalation_after_actions: int = 50  # Require human check-in after N actions


@dataclass
class SessionBudget:
    """Tracks cumulative resource usage within a session."""
    session_id: str
    started_at: float = field(default_factory=time.monotonic)
    actions_evaluated: int = 0
    actions_allowed: int = 0
    actions_denied: int = 0
    actions_gated: int = 0
    cost_usd: float = 0.0
    total_duration_ms: float = 0.0
    retries: int = 0
    _escalation_fired: bool = field(default=False, repr=False)

    def elapsed_ms(self) -> float:
        return (time.monotonic() - self.started_at) * 1000.0


@dataclass
class EscalationEvent:
    """Triggered when session crosses a threshold."""
    session_id: str
    threshold: str       # "max_actions", "max_denials", "max_cost", "max_duration", "escalation"
    current_value: Any
    limit_value: Any
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

class SessionBudgetTracker:
    """Track and enforce session-level budgets.

    Usage::

        limits = SessionLimits(max_actions=50)
        tracker = SessionBudgetTracker(limits)
        budget = SessionBudget(session_id="sess-1")

        # Before each action:
        events = tracker.check(budget)
        should_stop, reason = tracker.should_terminate(budget)

        # After each action:
        tracker.record_action(budget, allowed=True, duration_ms=120.5)
    """

    def __init__(self, limits: SessionLimits | None = None) -> None:
        self.limits = limits or SessionLimits()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_action(
        self,
        budget: SessionBudget,
        *,
        allowed: bool,
        duration_ms: float = 0.0,
        cost_usd: float = 0.0,
        gated: bool = False,
    ) -> None:
        """Record the outcome of an action evaluation."""
        budget.actions_evaluated += 1
        budget.total_duration_ms += duration_ms
        budget.cost_usd += cost_usd

        if gated:
            budget.actions_gated += 1
        elif allowed:
            budget.actions_allowed += 1
        else:
            budget.actions_denied += 1

    def record_retry(self, budget: SessionBudget) -> None:
        """Record a retry attempt."""
        budget.retries += 1

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def check(self, budget: SessionBudget) -> list[EscalationEvent]:
        """Check all thresholds and return any triggered events.

        Does NOT mutate the budget. Safe to call multiple times.
        """
        events: list[EscalationEvent] = []
        lim = self.limits

        if budget.actions_evaluated >= lim.max_actions:
            events.append(EscalationEvent(
                session_id=budget.session_id,
                threshold="max_actions",
                current_value=budget.actions_evaluated,
                limit_value=lim.max_actions,
            ))

        if budget.actions_denied >= lim.max_denials:
            events.append(EscalationEvent(
                session_id=budget.session_id,
                threshold="max_denials",
                current_value=budget.actions_denied,
                limit_value=lim.max_denials,
            ))

        if budget.cost_usd >= lim.max_cost_usd:
            events.append(EscalationEvent(
                session_id=budget.session_id,
                threshold="max_cost",
                current_value=budget.cost_usd,
                limit_value=lim.max_cost_usd,
            ))

        elapsed = budget.elapsed_ms()
        if elapsed >= lim.max_duration_ms:
            events.append(EscalationEvent(
                session_id=budget.session_id,
                threshold="max_duration",
                current_value=elapsed,
                limit_value=lim.max_duration_ms,
            ))

        if (
            not budget._escalation_fired
            and budget.actions_evaluated >= lim.escalation_after_actions
        ):
            events.append(EscalationEvent(
                session_id=budget.session_id,
                threshold="escalation",
                current_value=budget.actions_evaluated,
                limit_value=lim.escalation_after_actions,
            ))
            budget._escalation_fired = True

        return events

    def should_terminate(self, budget: SessionBudget) -> tuple[bool, str]:
        """Return (True, reason) if session must be terminated."""
        lim = self.limits

        if budget.actions_evaluated >= lim.max_actions:
            return True, f"Session action limit reached ({budget.actions_evaluated}/{lim.max_actions})"

        if budget.actions_denied >= lim.max_denials:
            return True, f"Session denial limit reached ({budget.actions_denied}/{lim.max_denials})"

        if budget.cost_usd >= lim.max_cost_usd:
            return True, f"Session cost limit reached (${budget.cost_usd:.4f}/${lim.max_cost_usd:.2f})"

        elapsed = budget.elapsed_ms()
        if elapsed >= lim.max_duration_ms:
            return True, f"Session duration limit reached ({elapsed:.0f}ms/{lim.max_duration_ms:.0f}ms)"

        return False, ""

    def should_escalate(self, budget: SessionBudget) -> bool:
        """Return True if escalation threshold is crossed.

        Sets _escalation_fired on first trigger so it only fires once.
        """
        if budget._escalation_fired:
            return False
        if budget.actions_evaluated >= self.limits.escalation_after_actions:
            budget._escalation_fired = True
            return True
        return False

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self, budget: SessionBudget) -> dict[str, Any]:
        """Return a serializable snapshot of the budget."""
        return {
            "session_id": budget.session_id,
            "actions_evaluated": budget.actions_evaluated,
            "actions_allowed": budget.actions_allowed,
            "actions_denied": budget.actions_denied,
            "actions_gated": budget.actions_gated,
            "cost_usd": budget.cost_usd,
            "total_duration_ms": budget.total_duration_ms,
            "retries": budget.retries,
            "elapsed_ms": budget.elapsed_ms(),
        }
