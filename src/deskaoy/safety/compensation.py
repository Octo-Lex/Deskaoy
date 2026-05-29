"""Compensation Plans — structured undo with per-action rollback strategies.

Inspired by det-acp's RollbackManager. Each action registers an undo strategy
before execution. When rollback is needed, the engine builds a LIFO
compensation plan and executes it best-effort against the surface adapter.

Every rollback step is recorded in the evidence ledger (if available).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from deskaoy.results.types import ActionResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class CompensatingAction:
    """A single undo step in a compensation plan."""

    action: str                # Original action name: "click", "fill", "type_text"
    target: str                # Original target
    inverse_action: str        # What to do: "fill", "key_press", "scroll", "navigate", "none"
    inverse_params: dict       # Params for the inverse action
    strategy: str              # "restore_state", "delete_created", "compensate", "none"
    can_rollback: bool         # Whether we have enough info to undo
    priority: int = 0          # Higher = undo first (LIFO by default)

    # Metadata for tracing
    execution_id: str = ""
    registered_at: str = ""


@dataclass
class CompensationPlan:
    """Ordered list of undo steps for a session or execution."""

    plan_id: str
    execution_id: str
    steps: list[CompensatingAction]
    created_at: str


@dataclass
class RollbackStepResult:
    """Result of executing a single rollback step."""

    action: str
    target: str
    success: bool
    description: str
    error: str = ""


@dataclass
class RollbackReport:
    """Summary of a full rollback execution."""

    plan_id: str
    total_steps: int
    succeeded: int
    failed: int
    skipped: int
    results: list[RollbackStepResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Inverse Action Mapping
# ---------------------------------------------------------------------------

# Actions that are read-only (no side effects, no undo needed)
_READ_ONLY_ACTIONS = frozenset({"screenshot", "snapshot", "evaluate"})

# Actions whose side effects cannot be meaningfully reversed
# (clicking triggers unknown state changes, key_press may submit forms, etc.)
_IRREVERSIBLE_ACTIONS = frozenset({"click", "key_press"})

# Actions whose before-state we can capture and restore
_REVERSIBLE_ACTIONS = frozenset({"fill", "type_text", "scroll", "navigate"})


def _compute_inverse(
    action: str,
    target: str,
    before_state: dict,
    params: dict,
) -> CompensatingAction:
    """Compute the inverse (undo) for a single action.

    Returns a CompensatingAction with the appropriate strategy.
    """
    now = _iso_now()

    # Read-only actions
    if action in _READ_ONLY_ACTIONS:
        return CompensatingAction(
            action=action,
            target=target,
            inverse_action="none",
            inverse_params={},
            strategy="none",
            can_rollback=True,  # No rollback needed — read-only
            priority=0,
            registered_at=now,
        )

    # Irreversible actions
    if action in _IRREVERSIBLE_ACTIONS:
        return CompensatingAction(
            action=action,
            target=target,
            inverse_action="none",
            inverse_params={},
            strategy="none",
            can_rollback=False,
            priority=0,
            registered_at=now,
        )

    # fill → restore previous value
    if action == "fill":
        before_value = before_state.get("value", before_state.get("text", ""))
        return CompensatingAction(
            action=action,
            target=target,
            inverse_action="fill",
            inverse_params={"target": target, "value": before_value},
            strategy="restore_state",
            can_rollback=True,
            priority=10,
            registered_at=now,
        )

    # type_text → restore previous text via fill
    if action == "type_text":
        before_value = before_state.get("value", before_state.get("text", ""))
        focused = before_state.get("focus", target)
        return CompensatingAction(
            action=action,
            target=target,
            inverse_action="fill",
            inverse_params={"target": focused, "value": before_value},
            strategy="restore_state",
            can_rollback=True,
            priority=10,
            registered_at=now,
        )

    # scroll → reverse direction
    if action == "scroll":
        original_direction = params.get("direction", "down")
        opposite = {
            "down": "up", "up": "down",
            "left": "right", "right": "left",
        }.get(original_direction, "up")
        amount = params.get("amount", 500)
        return CompensatingAction(
            action=action,
            target=target,
            inverse_action="scroll",
            inverse_params={"direction": opposite, "amount": amount},
            strategy="restore_state",
            can_rollback=True,
            priority=5,
            registered_at=now,
        )

    # navigate → go back to previous URL
    if action == "navigate":
        previous_url = before_state.get("url", before_state.get("current_url", ""))
        return CompensatingAction(
            action=action,
            target=target,
            inverse_action="navigate",
            inverse_params={"url": previous_url},
            strategy="restore_state",
            can_rollback=bool(previous_url),
            priority=15,
            registered_at=now,
        )

    # Unknown action — conservative default
    return CompensatingAction(
        action=action,
        target=target,
        inverse_action="none",
        inverse_params={},
        strategy="none",
        can_rollback=False,
        priority=0,
        registered_at=now,
    )


# ---------------------------------------------------------------------------
# Surface Protocol (for type hints — avoids circular imports)
# ---------------------------------------------------------------------------

@runtime_checkable
class RollbackSurface(Protocol):
    """Minimal surface interface needed for rollback execution."""

    async def fill(self, target: str, value: str, **kwargs: Any) -> ActionResult: ...
    async def scroll(self, direction: str, amount: int = 500, **kwargs: Any) -> ActionResult: ...
    async def navigate(self, url: str) -> ActionResult: ...


# ---------------------------------------------------------------------------
# CompensationEngine
# ---------------------------------------------------------------------------

class CompensationEngine:
    """Build and execute compensation plans.

    Before each action, call register() with the before-state.
    When rollback is needed, call build_plan() then execute_plan().
    """

    def __init__(
        self,
        surface: RollbackSurface | None = None,
        ledger: Any = None,
    ) -> None:
        self._surface = surface
        self._ledger = ledger  # EvidenceLedger (optional)
        # execution_id → list of CompensatingAction
        self._registry: dict[str, list[CompensatingAction]] = {}

    @property
    def surface(self) -> RollbackSurface | None:
        return self._surface

    @surface.setter
    def surface(self, value: RollbackSurface | None) -> None:
        self._surface = value

    # ─── Registration ─────────────────────────────

    def register(
        self,
        execution_id: str,
        action: str,
        target: str,
        before_state: dict,
        params: dict | None = None,
    ) -> CompensatingAction:
        """Register an undo strategy for an action about to be executed.

        Call BEFORE the adapter method to capture the before-state.
        """
        params = params or {}
        comp = _compute_inverse(action, target, before_state, params)
        comp.execution_id = execution_id

        if execution_id not in self._registry:
            self._registry[execution_id] = []
        self._registry[execution_id].append(comp)

        return comp

    # ─── Plan Building ────────────────────────────

    def build_plan(self, execution_id: str) -> CompensationPlan:
        """Build a compensation plan from registered actions.

        Steps are ordered in reverse (LIFO — last action undone first).
        Read-only actions (strategy="none", can_rollback=True) are kept
        for traceability but skipped during execution.
        """
        actions = self._registry.get(execution_id, [])
        # Reverse order — LIFO
        steps = list(reversed(actions))

        return CompensationPlan(
            plan_id=uuid.uuid4().hex[:12],
            execution_id=execution_id,
            steps=steps,
            created_at=_iso_now(),
        )

    def get_registered_count(self, execution_id: str) -> int:
        """Return number of registered actions for an execution."""
        return len(self._registry.get(execution_id, []))

    # ─── Plan Execution ──────────────────────────

    async def execute_plan(self, plan: CompensationPlan) -> RollbackReport:
        """Execute a compensation plan against the surface adapter.

        Best-effort: continues even if individual rollbacks fail.
        Records every rollback step in the evidence ledger.
        """
        results: list[RollbackStepResult] = []
        succeeded = 0
        failed = 0
        skipped = 0

        for step in plan.steps:
            # Skip read-only actions (screenshot, snapshot, evaluate)
            if step.strategy == "none" and step.can_rollback:
                skipped += 1
                results.append(RollbackStepResult(
                    action=step.action,
                    target=step.target,
                    success=True,
                    description="Skipped — read-only action",
                ))
                continue

            # Skip irreversible actions (click, key_press)
            if not step.can_rollback:
                skipped += 1
                results.append(RollbackStepResult(
                    action=step.action,
                    target=step.target,
                    success=False,
                    description=f"Skipped — {step.action} is not reversible",
                ))
                continue

            # Execute the inverse action
            result = await self._execute_step(step)
            results.append(result)

            if result.success:
                succeeded += 1
            else:
                failed += 1

            # Record in evidence ledger
            await self._record_rollback(plan.execution_id, step, result)

        return RollbackReport(
            plan_id=plan.plan_id,
            total_steps=len(plan.steps),
            succeeded=succeeded,
            failed=failed,
            skipped=skipped,
            results=results,
        )

    async def _execute_step(self, step: CompensatingAction) -> RollbackStepResult:
        """Execute a single rollback step against the surface."""
        if self._surface is None:
            return RollbackStepResult(
                action=step.action,
                target=step.target,
                success=False,
                description="No surface adapter available",
                error="surface_not_set",
            )

        try:
            if step.inverse_action == "fill":
                result = await self._surface.fill(
                    step.inverse_params.get("target", step.target),
                    step.inverse_params.get("value", ""),
                )
                return RollbackStepResult(
                    action=step.action,
                    target=step.target,
                    success=result.ok,
                    description="Restored value via fill" if result.ok else "fill() returned not ok",
                    error="" if result.ok else str(result.data),
                )

            elif step.inverse_action == "scroll":
                result = await self._surface.scroll(
                    step.inverse_params.get("direction", "up"),
                    step.inverse_params.get("amount", 500),
                )
                return RollbackStepResult(
                    action=step.action,
                    target=step.target,
                    success=result.ok,
                    description="Reversed scroll" if result.ok else "scroll() returned not ok",
                    error="" if result.ok else str(result.data),
                )

            elif step.inverse_action == "navigate":
                url = step.inverse_params.get("url", "")
                if not url:
                    return RollbackStepResult(
                        action=step.action,
                        target=step.target,
                        success=False,
                        description="No previous URL to navigate back to",
                        error="missing_url",
                    )
                result = await self._surface.navigate(url)
                return RollbackStepResult(
                    action=step.action,
                    target=step.target,
                    success=result.ok,
                    description=f"Navigated back to {url}" if result.ok else "navigate() returned not ok",
                    error="" if result.ok else str(result.data),
                )

            else:
                return RollbackStepResult(
                    action=step.action,
                    target=step.target,
                    success=False,
                    description=f"Unknown inverse action: {step.inverse_action}",
                    error="unknown_inverse",
                )

        except Exception as exc:
            return RollbackStepResult(
                action=step.action,
                target=step.target,
                success=False,
                description="Rollback threw an exception",
                error=str(exc),
            )

    async def _record_rollback(
        self,
        execution_id: str,
        step: CompensatingAction,
        result: RollbackStepResult,
    ) -> None:
        """Record a rollback step in the evidence ledger (if available)."""
        if self._ledger is None:
            return
        try:
            await self._ledger.append(
                execution_id,
                "action:rollback",
                {
                    "action": step.action,
                    "target": step.target,
                    "inverse_action": step.inverse_action,
                    "success": result.success,
                    "error": result.error,
                },
            )
        except Exception as exc:
            logger.warning("Failed to record rollback in ledger: %s", exc)

    # ─── Cleanup ─────────────────────────────────

    def clear(self, execution_id: str) -> None:
        """Clear registered actions for an execution."""
        self._registry.pop(execution_id, None)

    def clear_all(self) -> None:
        """Clear all registered actions."""
        self._registry.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    """UTC ISO-8601 timestamp."""
    return datetime.now(UTC).isoformat()
