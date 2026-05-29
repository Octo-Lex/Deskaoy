"""CaptureGate — concurrency protection for screenshot/observation operations.

Ensures only one capture (screenshot or observation) runs at a time using
an asyncio.Lock-based mutex. Prevents resource contention and deadlocks
via a configurable queue depth limit and timeout.

HB-01: Capture gate must not deadlock — timeout after 10s by default.

Usage::

    gate = CaptureGate()

    async with gate.acquire():
        screenshot = await adapter.screenshot()

    # Or use the decorator on adapter methods
    metrics = gate.get_metrics()
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CaptureMetrics:
    """Metrics snapshot for the capture gate.

    Fields:
        capture_count: Total successful captures completed.
        wait_time_ms: Cumulative wait time in milliseconds across all captures.
        timeout_count: Number of captures that timed out waiting for the lock.
        active_captures: Currently running captures (0 or 1 with single lock).
        pending_captures: Captures waiting for the lock.
    """

    capture_count: int = 0
    wait_time_ms: float = 0.0
    timeout_count: int = 0
    active_captures: int = 0
    pending_captures: int = 0


class CaptureGate:
    """Concurrency gate for screenshot/observation operations.

    Provides mutual exclusion for capture operations with:
      - asyncio.Lock-based mutex (only one capture at a time)
      - Queue depth limit (max pending captures)
      - Timeout protection (prevents deadlocks per HB-01)
      - Cumulative metrics tracking

    Args:
        queue_depth: Maximum number of pending captures allowed.
            Default 5. When exceeded, ``TimeoutError`` is raised immediately.
        timeout_seconds: Maximum time to wait for lock acquisition.
            Default 10.0 per HB-01.
    """

    def __init__(
        self,
        *,
        queue_depth: int = 5,
        timeout_seconds: float = 10.0,
    ) -> None:
        if queue_depth < 1:
            raise ValueError(f"queue_depth must be >= 1, got {queue_depth}")
        if timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds must be > 0, got {timeout_seconds}")

        self._lock = asyncio.Lock()
        self._queue_depth = queue_depth
        self._timeout_seconds = timeout_seconds

        # Metrics
        self._capture_count = 0
        self._wait_time_ms = 0.0
        self._timeout_count = 0

    @property
    def queue_depth(self) -> int:
        """Maximum pending captures."""
        return self._queue_depth

    @property
    def timeout_seconds(self) -> float:
        """Lock acquisition timeout in seconds."""
        return self._timeout_seconds

    @property
    def is_locked(self) -> bool:
        """Whether the gate is currently held."""
        return self._lock.locked()

    @property
    def pending_count(self) -> int:
        """Number of waiters for the lock."""
        waiters = getattr(self._lock, '_waiters', None)
        if waiters is None:
            return 0
        return len(waiters)

    def get_metrics(self) -> CaptureMetrics:
        """Return current metrics snapshot."""
        return CaptureMetrics(
            capture_count=self._capture_count,
            wait_time_ms=self._wait_time_ms,
            timeout_count=self._timeout_count,
            active_captures=1 if self._lock.locked() else 0,
            pending_captures=self.pending_count,
        )

    def reset_metrics(self) -> None:
        """Reset all metrics counters. Useful for testing."""
        self._capture_count = 0
        self._wait_time_ms = 0.0
        self._timeout_count = 0

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        """Acquire the capture gate as an async context manager.

        Raises:
            CaptureQueueFullError: If the queue depth limit is exceeded.
            asyncio.TimeoutError: If lock acquisition times out (HB-01).

        Usage::

            async with gate.acquire():
                result = await adapter.screenshot()
        """
        # Check queue depth before waiting
        if self._lock.locked() and self.pending_count >= self._queue_depth - 1:
            self._timeout_count += 1
            raise CaptureQueueFullError(
                f"Capture queue full: {self._queue_depth} pending captures"
            )

        wait_start = time.monotonic()

        try:
            await asyncio.wait_for(
                self._lock.acquire(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            self._timeout_count += 1
            logger.warning(
                "Capture gate timeout after %.1fs (HB-01 protection)",
                self._timeout_seconds,
            )
            raise

        wait_elapsed_ms = (time.monotonic() - wait_start) * 1000.0
        self._wait_time_ms += wait_elapsed_ms

        try:
            yield
        finally:
            self._capture_count += 1
            self._lock.release()

    async def run(self, coro: Any) -> Any:
        """Run a coroutine inside the capture gate.

        Convenience method that acquires the gate, runs the coroutine,
        and releases the gate automatically.

        Args:
            coro: Awaitable to execute within the gate.

        Returns:
            The result of the coroutine.

        Raises:
            CaptureQueueFullError: If the queue depth limit is exceeded.
            asyncio.TimeoutError: If lock acquisition times out.
        """
        async with self.acquire():
            return await coro


class CaptureQueueFullError(Exception):
    """Raised when the capture queue depth limit is exceeded."""
    pass
