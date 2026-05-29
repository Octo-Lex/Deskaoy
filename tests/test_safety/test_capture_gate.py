"""Tests for CaptureGate — concurrency protection (BATCH-31)."""
from __future__ import annotations

import asyncio

import pytest

from deskaoy.safety.capture_gate import (
    CaptureGate,
    CaptureMetrics,
    CaptureQueueFullError,
)


# ── Construction ──────────────────────────────────────────────────────

class TestCaptureGateConstruction:
    """Test CaptureGate construction and configuration."""

    def test_default_config(self):
        gate = CaptureGate()
        assert gate.queue_depth == 5
        assert gate.timeout_seconds == 10.0
        assert not gate.is_locked

    def test_custom_config(self):
        gate = CaptureGate(queue_depth=10, timeout_seconds=5.0)
        assert gate.queue_depth == 10
        assert gate.timeout_seconds == 5.0

    def test_invalid_queue_depth(self):
        with pytest.raises(ValueError, match="queue_depth"):
            CaptureGate(queue_depth=0)

    def test_invalid_timeout(self):
        with pytest.raises(ValueError, match="timeout_seconds"):
            CaptureGate(timeout_seconds=0)


# ── Mutual Exclusion ──────────────────────────────────────────────────

class TestCaptureGateMutex:
    """Test mutual exclusion behavior."""

    @pytest.mark.asyncio
    async def test_single_acquire_release(self):
        gate = CaptureGate()
        async with gate.acquire():
            assert gate.is_locked
        assert not gate.is_locked

    @pytest.mark.asyncio
    async def test_sequential_access(self):
        """Two coroutines access sequentially — no overlap."""
        gate = CaptureGate()
        order: list[str] = []

        async def worker(name: str):
            async with gate.acquire():
                order.append(f"{name}_start")
                await asyncio.sleep(0.01)
                order.append(f"{name}_end")

        await asyncio.gather(worker("A"), worker("B"))
        # A finishes before B starts (or vice versa), no interleaving
        assert order in [
            ["A_start", "A_end", "B_start", "B_end"],
            ["B_start", "B_end", "A_start", "A_end"],
        ]

    @pytest.mark.asyncio
    async def test_run_helper(self):
        """run() wraps a coroutine inside the gate."""
        gate = CaptureGate()

        async def my_task():
            return 42

        result = await gate.run(my_task())
        assert result == 42


# ── Timeout Protection (HB-01) ────────────────────────────────────────

class TestCaptureGateTimeout:
    """Test timeout behavior — HB-01: must not deadlock."""

    @pytest.mark.asyncio
    async def test_timeout_on_lock_contention(self):
        """Lock held for longer than timeout → TimeoutError."""
        gate = CaptureGate(timeout_seconds=0.1)

        async def holder():
            async with gate.acquire():
                await asyncio.sleep(1.0)  # Hold lock for 1s

        async def waiter():
            await asyncio.sleep(0.02)  # Let holder acquire first
            async with gate.acquire():
                pass

        holder_task = asyncio.create_task(holder())
        await asyncio.sleep(0.05)  # Let holder get lock

        with pytest.raises(asyncio.TimeoutError):
            await waiter()

        holder_task.cancel()
        try:
            await holder_task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_timeout_increments_metric(self):
        """Timeout count increments on TimeoutError."""
        gate = CaptureGate(timeout_seconds=0.05)

        # Hold the lock
        async with gate.acquire():
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(gate.acquire().__aenter__(), timeout=0.2)

        metrics = gate.get_metrics()
        assert metrics.timeout_count == 1


# ── Metrics ────────────────────────────────────────────────────────────

class TestCaptureGateMetrics:
    """Test metrics tracking."""

    @pytest.mark.asyncio
    async def test_capture_count_increments(self):
        gate = CaptureGate()
        async with gate.acquire():
            pass
        async with gate.acquire():
            pass
        metrics = gate.get_metrics()
        assert metrics.capture_count == 2

    @pytest.mark.asyncio
    async def test_wait_time_tracked(self):
        gate = CaptureGate()
        # First acquire: no wait
        async with gate.acquire():
            pass
        metrics = gate.get_metrics()
        assert metrics.wait_time_ms >= 0.0

    @pytest.mark.asyncio
    async def test_reset_metrics(self):
        gate = CaptureGate()
        async with gate.acquire():
            pass
        gate.reset_metrics()
        metrics = gate.get_metrics()
        assert metrics.capture_count == 0
        assert metrics.wait_time_ms == 0.0
        assert metrics.timeout_count == 0

    @pytest.mark.asyncio
    async def test_metrics_snapshot_type(self):
        gate = CaptureGate()
        metrics = gate.get_metrics()
        assert isinstance(metrics, CaptureMetrics)
        assert metrics.active_captures == 0
        assert metrics.pending_captures == 0
