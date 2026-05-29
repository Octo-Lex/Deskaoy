"""TimeoutGuard — shared deadline tracker for multi-step operations.

Adopted from Stagehand's ``createTimeoutGuard()`` pattern. Unlike raw
``asyncio.wait_for()``, this guard:

- Shares a single deadline across N steps
- Reports remaining time for adaptive behavior
- Can be passed to sub-operations
- Supports child guards capped by the parent's remaining time

No external deps — pure stdlib.
"""

from __future__ import annotations

import asyncio
import time


class TimeoutGuard:
    """Shared deadline tracker for multi-step operations.

    Usage::

        guard = TimeoutGuard(total_timeout_ms=30_000)

        # Each step checks remaining time
        guard.check()  # raises TimeoutError if exhausted

        remaining = guard.remaining_ms
        result = await asyncio.wait_for(some_op(), timeout=remaining / 1000)

        # Create child guards for sub-operations
        child = guard.child(5000)  # 5s, but capped by parent
    """

    def __init__(self, total_timeout_ms: float) -> None:
        self._deadline = time.monotonic() + total_timeout_ms / 1000.0
        self._total_ms = total_timeout_ms

    def check(self) -> None:
        """Raise ``TimeoutError`` if the deadline has passed."""
        if time.monotonic() >= self._deadline:
            raise TimeoutError(
                f"Timeout guard exhausted "
                f"(allocated {self._total_ms:.0f}ms)"
            )

    @property
    def remaining_ms(self) -> float:
        """Milliseconds remaining until deadline."""
        left = (self._deadline - time.monotonic()) * 1000.0
        return max(0.0, left)

    @property
    def exhausted(self) -> bool:
        """True if the deadline has passed."""
        return time.monotonic() >= self._deadline

    def child(self, timeout_ms: float) -> TimeoutGuard:
        """Create a child guard capped by this guard's remaining time.

        The child's deadline is ``min(parent_deadline, now + timeout_ms)``.
        This prevents a child from extending beyond the parent's budget.
        """
        remaining = self.remaining_ms
        capped_ms = min(timeout_ms, remaining)
        child = TimeoutGuard(capped_ms)
        # Also cap by parent's actual deadline
        child._deadline = min(child._deadline, self._deadline)
        return child

    async def sleep(self, seconds: float) -> None:
        """Sleep, but wake early if deadline passes.

        Uses ``asyncio.sleep`` for the shorter of the requested duration
        and the remaining time. Raises ``TimeoutError`` if the deadline
        passes during the sleep.
        """
        remaining_s = self.remaining_ms / 1000.0
        actual_s = min(seconds, remaining_s)

        if actual_s <= 0:
            raise TimeoutError("Timeout guard exhausted during sleep")

        try:
            await asyncio.sleep(actual_s)
        finally:
            if self.exhausted:
                raise TimeoutError(
                    "Timeout guard exhausted during sleep"
                )

    def __repr__(self) -> str:
        state = "exhausted" if self.exhausted else "active"
        return (
            f"TimeoutGuard({self._total_ms:.0f}ms, "
            f"remaining={self.remaining_ms:.0f}ms, {state})"
        )
