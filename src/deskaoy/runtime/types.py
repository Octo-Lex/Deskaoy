"""Runtime Execution Hardening — Types.

All types for the B38-aligned runtime execution layer.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Attempt lifecycle
# ---------------------------------------------------------------------------

class RuntimeAttemptState(StrEnum):
    """States for a runtime execution attempt.

    State machine (forward only):
        PENDING → PREFLIGHT_PASSED → RUNNING → COMPLETED | FAILED | CANCELLED | TIMED_OUT | BLOCKED
    """
    PENDING = "pending"
    PREFLIGHT_PASSED = "preflight_passed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    BLOCKED = "blocked"


# Terminal states — once entered, no further transitions allowed
_TERMINAL_STATES = frozenset({
    RuntimeAttemptState.COMPLETED,
    RuntimeAttemptState.FAILED,
    RuntimeAttemptState.CANCELLED,
    RuntimeAttemptState.TIMED_OUT,
    RuntimeAttemptState.BLOCKED,
})

# Valid transitions: {from_state: {allowed_to_states}}
_VALID_TRANSITIONS = {
    RuntimeAttemptState.PENDING: {RuntimeAttemptState.PREFLIGHT_PASSED, RuntimeAttemptState.BLOCKED, RuntimeAttemptState.CANCELLED},
    RuntimeAttemptState.PREFLIGHT_PASSED: {RuntimeAttemptState.RUNNING, RuntimeAttemptState.BLOCKED, RuntimeAttemptState.CANCELLED},
    RuntimeAttemptState.RUNNING: {RuntimeAttemptState.COMPLETED, RuntimeAttemptState.FAILED, RuntimeAttemptState.CANCELLED, RuntimeAttemptState.TIMED_OUT},
}


class RuntimeAttempt:
    """A single execution attempt with state lifecycle enforcement."""

    def __init__(
        self,
        execution_id: str,
        *,
        attempt_id: str | None = None,
    ) -> None:
        self.attempt_id = attempt_id or str(uuid.uuid4())
        self.execution_id = execution_id
        self._state = RuntimeAttemptState.PENDING
        self.preflight_result: PreflightResult | None = None
        self.receipt: RuntimeExecutionReceipt | None = None
        self.created_at = time.time()
        self.updated_at = self.created_at

    @property
    def state(self) -> RuntimeAttemptState:
        return self._state

    def transition(self, new_state: RuntimeAttemptState) -> None:
        """Transition to a new state. Raises ValueError if invalid."""
        if self._state in _TERMINAL_STATES:
            raise ValueError(
                f"Attempt {self.attempt_id} is in terminal state "
                f"'{self._state.value}'. No further transitions allowed."
            )
        allowed = _VALID_TRANSITIONS.get(self._state, set())
        if new_state not in allowed:
            raise ValueError(
                f"Invalid transition: {self._state.value} → {new_state.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
        self._state = new_state
        self.updated_at = time.time()

    def is_terminal(self) -> bool:
        return self._state in _TERMINAL_STATES

    def set_preflight_result(self, result: PreflightResult) -> None:
        self.preflight_result = result

    def set_receipt(self, receipt: RuntimeExecutionReceipt) -> None:
        self.receipt = receipt


# ---------------------------------------------------------------------------
# Policy obligations
# ---------------------------------------------------------------------------

class PolicyObligation(StrEnum):
    """Obligations that policy can require before execution."""
    DRY_RUN_REQUIRED = "dry_run_required"
    APPROVAL_REQUIRED = "approval_required"
    QUARANTINE_ON_FAILURE = "quarantine_on_failure"
    SANDBOX_REQUIRED = "sandbox_required"
    LOG_FULL_PAYLOAD = "log_full_payload"


# ---------------------------------------------------------------------------
# Adapter capabilities
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AdapterCapabilities:
    """Declarative capabilities of a surface adapter.

    Adapters declare what they support. The preflight checks these
    declarations against the requested action's requirements.
    """
    supports_mouse: bool = True
    supports_keyboard: bool = True
    supports_screen_capture: bool = True
    supports_accessibility_read: bool = True
    supports_filesystem: bool = False
    supports_network: bool = False
    supports_dry_run: bool = True
    supports_sandboxing: bool = False
    adapter_id: str = ""
    adapter_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "supports_mouse": self.supports_mouse,
            "supports_keyboard": self.supports_keyboard,
            "supports_screen_capture": self.supports_screen_capture,
            "supports_accessibility_read": self.supports_accessibility_read,
            "supports_filesystem": self.supports_filesystem,
            "supports_network": self.supports_network,
            "supports_dry_run": self.supports_dry_run,
            "supports_sandboxing": self.supports_sandboxing,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
        }

    def fingerprint(self) -> str:
        """SHA-256 hash of capability declarations."""
        raw = "|".join(f"{k}={v}" for k, v in sorted(self.to_dict().items()))
        return hashlib.sha256(raw.encode()).hexdigest()


# Default capabilities for Windows desktop adapter
WINDOWS_CAPABILITIES = AdapterCapabilities(
    supports_mouse=True,
    supports_keyboard=True,
    supports_screen_capture=True,
    supports_accessibility_read=True,
    supports_filesystem=False,
    supports_network=False,
    supports_dry_run=True,
    supports_sandboxing=False,
    adapter_id="windows-desktop",
    adapter_version="1.0",
)


# ---------------------------------------------------------------------------
# Resource budget
# ---------------------------------------------------------------------------

@dataclass
class RuntimeResourceBudget:
    """Resource limits for a single execution."""
    timeout_ms: int = 60_000
    max_output_bytes: int = 1_048_576  # 1MB
    max_actions: int = 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeout_ms": self.timeout_ms,
            "max_output_bytes": self.max_output_bytes,
            "max_actions": self.max_actions,
        }


# ---------------------------------------------------------------------------
# Preflight types
# ---------------------------------------------------------------------------

@dataclass
class PreflightCheck:
    """Result of a single preflight check."""
    check_id: str
    name: str
    passed: bool
    message: str = ""


@dataclass
class PreflightResult:
    """Result of the full canonical preflight."""
    passed: bool
    checks: list[PreflightCheck] = field(default_factory=list)
    fingerprint: str = ""
    obligations_required: list[PolicyObligation] = field(default_factory=list)
    blocked_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [{"check_id": c.check_id, "name": c.name, "passed": c.passed, "message": c.message} for c in self.checks],
            "fingerprint": self.fingerprint,
            "obligations_required": [o.value for o in self.obligations_required],
            "blocked_reason": self.blocked_reason,
        }


# ---------------------------------------------------------------------------
# Truthful receipt
# ---------------------------------------------------------------------------

@dataclass
class RuntimeExecutionReceipt:
    """Truthful receipt for a runtime execution attempt.

    Once created, this is immutable. Every field is auto-generated.
    The truth_message accurately reflects what happened.

    Reference: AI-OS Batch 38 — "runtime_execution_performed, simulated,
    dry_run, side_effects_performed with hard-coded truth messages."
    """
    execution_id: str
    attempt_id: str
    attempt_state: RuntimeAttemptState
    truth_message: str
    runtime_execution_performed: bool
    simulated: bool
    dry_run: bool
    side_effects_performed: bool
    preflight_passed: bool
    preflight_fingerprint: str = ""
    obligations_checked: list[str] = field(default_factory=list)
    obligations_blocked: list[str] = field(default_factory=list)
    resource_budget: RuntimeResourceBudget | None = None
    timestamp: float = field(default_factory=time.time)
    _frozen: bool = field(default=False, repr=False)

    def freeze(self) -> None:
        """Make this receipt immutable."""
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_frozen", False) and name != "_frozen":
            raise AttributeError(f"Receipt is frozen. Cannot modify '{name}'.")
        super().__setattr__(name, value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "attempt_id": self.attempt_id,
            "attempt_state": self.attempt_state.value,
            "truth_message": self.truth_message,
            "runtime_execution_performed": self.runtime_execution_performed,
            "simulated": self.simulated,
            "dry_run": self.dry_run,
            "side_effects_performed": self.side_effects_performed,
            "preflight_passed": self.preflight_passed,
            "preflight_fingerprint": self.preflight_fingerprint,
            "obligations_checked": self.obligations_checked,
            "obligations_blocked": self.obligations_blocked,
            "resource_budget": self.resource_budget.to_dict() if self.resource_budget else None,
            "timestamp": self.timestamp,
        }


def make_truth_message(
    state: RuntimeAttemptState,
    *,
    dry_run: bool = False,
    simulated: bool = False,
    side_effects: bool = False,
) -> str:
    """Generate a truthful message for the receipt state."""
    if state == RuntimeAttemptState.BLOCKED:
        return "Execution was blocked. No adapter was invoked."
    if state == RuntimeAttemptState.PENDING:
        return "No execution has occurred."
    if state == RuntimeAttemptState.PREFLIGHT_PASSED:
        return "Preflight checks passed. Execution has not yet started."
    if state == RuntimeAttemptState.CANCELLED:
        return "Execution was cancelled. No side effects confirmed."
    if state == RuntimeAttemptState.TIMED_OUT:
        return "Execution timed out. Partial side effects may have occurred."
    if state == RuntimeAttemptState.FAILED:
        return "Execution failed. Side effects status uncertain."
    if state == RuntimeAttemptState.COMPLETED:
        if dry_run:
            return "Dry run completed. No side effects were performed."
        if simulated:
            return "Simulation completed. No side effects were performed."
        if side_effects:
            return "Execution completed with side effects performed."
        return "Execution completed. No side effects were performed."
    return f"Unknown state: {state.value}"
