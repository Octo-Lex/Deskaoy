"""Recovery bridge — make recovery attempts visible to AI-OS.

No invisible unbounded recovery loops.
Recovery attempt limits come from AI-OS policy when running inside AI-OS.
Repeated failures produce improvement/bug evidence for central submission.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Recovery event types
# ---------------------------------------------------------------------------

class RecoveryEventType(StrEnum):
    RETRY = "retry"
    RECOVERY = "recovery"
    STEP_WARNING = "step_warning"
    FAILURE_EVIDENCE = "failure_evidence"
    IMPROVEMENT_EVIDENCE = "improvement_evidence"


@dataclass
class RecoveryEvent:
    """A single recovery event reportable to AI-OS."""
    event_type: RecoveryEventType
    action: str = ""
    target: str = ""
    strategy: str = ""
    attempt_number: int = 0
    max_attempts: int = 3
    success: bool = False
    duration_ms: float = 0.0
    error_code: str = ""
    error_message: str = ""
    trace_id: str = ""
    span_id: str = ""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": str(self.event_type),
            "action": self.action,
            "target": self.target,
            "strategy": self.strategy,
            "attempt_number": self.attempt_number,
            "max_attempts": self.max_attempts,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "event_id": self.event_id,
        }


# ---------------------------------------------------------------------------
# Circuit breaker — prevents retry storms after consecutive failures
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Trip after *threshold* consecutive failures, cool down for *cooldown* seconds.

    States:
        closed  — normal operation, failures are counted
        open    — all retries blocked until cooldown elapses
        half-open — cooldown elapsed, one probe attempt allowed

    Pattern adapted from gogcli's ``internal/googleapi/circuitbreaker.go``.
    """

    def __init__(
        self,
        *,
        threshold: int = 5,
        cooldown: float = 30.0,
    ) -> None:
        self._threshold = threshold
        self._cooldown = cooldown
        self._failures = 0
        self._last_failure_time: float = 0.0
        self._open = False

    # ── Public API ───────────────────────────────

    def record_success(self) -> None:
        """Reset failure count and close the circuit."""
        was_open = self._open
        self._failures = 0
        self._open = False
        if was_open:
            logger.info("Circuit breaker reset (closed)")

    def record_failure(self) -> bool:
        """Record a failure.  Returns ``True`` if the circuit *just* opened."""
        self._failures += 1
        self._last_failure_time = time.monotonic()
        if self._failures >= self._threshold:
            just_opened = not self._open
            self._open = True
            if just_opened:
                logger.warning(
                    "Circuit breaker opened after %d failures", self._failures,
                )
            return just_opened
        return False

    def is_open(self) -> bool:
        """Is the circuit currently blocking retries?"""
        if not self._open:
            return False
        # Cooldown elapsed → half-open
        if time.monotonic() - self._last_failure_time > self._cooldown:
            self._open = False
            self._failures = 0
            logger.info("Circuit breaker attempting reset after cooldown")
            return False
        return True

    @property
    def state(self) -> str:
        """``'open'`` or ``'closed'``."""
        return "open" if self._open else "closed"

    @property
    def failure_count(self) -> int:
        return self._failures

    def reset(self) -> None:
        """Force-close the circuit (for testing)."""
        self._failures = 0
        self._open = False


# ---------------------------------------------------------------------------
# Retry policy — exponential backoff with jitter
# ---------------------------------------------------------------------------

@dataclass
class RetryPolicy:
    """Configurable retry delay strategy.

    Pattern adapted from gogcli's ``RetryTransport.calculateBackoff()``.
    """

    max_retries: int = 3
    base_delay: float = 1.0       # seconds
    max_delay: float = 30.0      # seconds
    jitter_fraction: float = 0.5 # 0-1, fraction of computed delay
    retryable_codes: set[str] = field(default_factory=lambda: {
        "timeout", "network_error", "rate_limited",
    })

    def delay_for_attempt(self, attempt: int) -> float:
        """Exponential backoff with random jitter.

        Returns delay in seconds for the *n*-th attempt (0-indexed).
        """
        raw = min(self.base_delay * (2 ** attempt), self.max_delay)
        jitter_amount = raw * self.jitter_fraction * random.random()
        return raw + jitter_amount

    def should_retry(self, error_code: str, attempt: int) -> bool:
        """Is this error retryable and under the attempt limit?"""
        return error_code in self.retryable_codes and attempt < self.max_retries


# ---------------------------------------------------------------------------
# Recovery event callback
# ---------------------------------------------------------------------------

RecoveryEventFn = Callable[[RecoveryEvent], Awaitable[None]]


# ---------------------------------------------------------------------------
# Recovery bridge
# ---------------------------------------------------------------------------

class RecoveryBridge:
    """Integration point for AI-OS recovery visibility.

    Tracks recovery attempts, emits events, and enforces bounds.
    """

    def __init__(
        self,
        *,
        emit_fn: RecoveryEventFn | None = None,
        max_attempts: int = 3,
        circuit_breaker: CircuitBreaker | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._emit_fn = emit_fn
        self._max_attempts = max_attempts
        self._circuit_breaker = circuit_breaker or CircuitBreaker()
        self._retry_policy = retry_policy or RetryPolicy()
        self._attempt_counts: dict[str, int] = {}  # action → count
        self._events: list[RecoveryEvent] = []

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    @max_attempts.setter
    def max_attempts(self, value: int) -> None:
        """Allow AI-OS policy to set the recovery attempt limit."""
        self._max_attempts = value

    def can_retry(self, action: str) -> bool:
        """Check whether a retry is allowed (circuit breaker + attempt limit)."""
        if self._circuit_breaker.is_open():
            return False
        count = self._attempt_counts.get(action, 0)
        return count < self._max_attempts

    def record_attempt(self, action: str, *, success: bool = False) -> int:
        """Record a recovery attempt and return the new count.

        Also feeds the circuit breaker: failure bumps the failure counter,
        success resets it.
        """
        count = self._attempt_counts.get(action, 0) + 1
        self._attempt_counts[action] = count
        if success:
            self._circuit_breaker.record_success()
        else:
            self._circuit_breaker.record_failure()
        return count

    async def emit(self, event: RecoveryEvent) -> None:
        """Emit a recovery event to AI-OS or store locally."""
        self._events.append(event)

        if self._emit_fn is not None:
            try:
                await self._emit_fn(event)
            except Exception as exc:
                logger.warning("Recovery event emit failed: %s", exc)
        else:
            logger.debug(
                "Recovery event: type=%s action=%s attempt=%d success=%s",
                event.event_type, event.action, event.attempt_number, event.success,
            )

    async def emit_retry(
        self,
        action: str,
        target: str,
        attempt: int,
        *,
        strategy: str = "",
        success: bool = False,
        duration_ms: float = 0.0,
        error_code: str = "",
        trace_id: str = "",
    ) -> None:
        """Convenience: emit a retry event."""
        event_type = RecoveryEventType.RECOVERY if success else RecoveryEventType.RETRY
        await self.emit(RecoveryEvent(
            event_type=event_type,
            action=action,
            target=target,
            strategy=strategy,
            attempt_number=attempt,
            max_attempts=self._max_attempts,
            success=success,
            duration_ms=duration_ms,
            error_code=error_code,
            trace_id=trace_id,
        ))

    async def emit_failure_evidence(
        self,
        action: str,
        target: str,
        error_message: str,
        *,
        attempt_count: int = 0,
        trace_id: str = "",
    ) -> None:
        """Emit failure evidence after exhausting recovery attempts."""
        await self.emit(RecoveryEvent(
            event_type=RecoveryEventType.FAILURE_EVIDENCE,
            action=action,
            target=target,
            error_message=error_message,
            attempt_number=attempt_count,
            max_attempts=self._max_attempts,
            trace_id=trace_id,
        ))

    # ── Retry with backoff ─────────────────────

    async def wait_and_retry(
        self,
        action: str,
        error_code: str,
    ) -> bool:
        """Check retry policy, sleep if retryable, record the attempt.

        Returns ``True`` if the caller should retry.
        """
        attempt = self._attempt_counts.get(action, 0)
        if not self._retry_policy.should_retry(error_code, attempt):
            return False
        if self._circuit_breaker.is_open():
            return False
        delay = self._retry_policy.delay_for_attempt(attempt)
        await asyncio.sleep(delay)
        self.record_attempt(action)
        return True

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """Access the underlying circuit breaker (for introspection)."""
        return self._circuit_breaker

    @property
    def retry_policy(self) -> RetryPolicy:
        """Access the retry policy (for introspection)."""
        return self._retry_policy

    @property
    def events(self) -> list[RecoveryEvent]:
        return list(self._events)

    def clear(self) -> None:
        self._events.clear()
        self._attempt_counts.clear()
