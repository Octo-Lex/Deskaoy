"""Tests for TimeoutGuard (v0.16.0 — Stagehand pattern)."""

from __future__ import annotations

import time

import pytest

from deskaoy.safety.timeout_guard import TimeoutGuard


class TestTimeoutGuard:
    def test_fresh_guard_has_remaining(self):
        guard = TimeoutGuard(5000)
        assert guard.remaining_ms > 4000  # ~5s remaining
        assert not guard.exhausted

    def test_remaining_decreases(self):
        guard = TimeoutGuard(200)
        r1 = guard.remaining_ms
        time.sleep(0.05)
        r2 = guard.remaining_ms
        assert r2 < r1

    def test_check_passes_when_time_remaining(self):
        guard = TimeoutGuard(5000)
        guard.check()  # Should not raise

    def test_check_raises_when_exhausted(self):
        guard = TimeoutGuard(0)
        guard._deadline = time.monotonic() - 1  # Force into past
        with pytest.raises(TimeoutError, match="exhausted"):
            guard.check()

    def test_exhausted_becomes_true(self):
        guard = TimeoutGuard(0.001)  # ~0 (sub-millisecond)
        # Force deadline into the past by manipulating internal state
        guard._deadline = time.monotonic() - 1
        assert guard.exhausted

    def test_child_capped_by_parent(self):
        parent = TimeoutGuard(1000)
        child = parent.child(5000)  # Request 5s, but parent only has ~1s
        assert child.remaining_ms <= 1100  # Capped near parent's budget

    def test_child_deadline_not_exceeds_parent(self):
        parent = TimeoutGuard(1000)
        child = parent.child(5000)
        assert child._deadline <= parent._deadline

    def test_repr(self):
        guard = TimeoutGuard(5000)
        r = repr(guard)
        assert "5000ms" in r
        assert "active" in r

    def test_repr_exhausted(self):
        guard = TimeoutGuard(0)
        guard._deadline = time.monotonic() - 1
        r = repr(guard)
        assert "exhausted" in r


class TestTimeoutGuardAsync:
    @pytest.mark.asyncio
    async def test_sleep_respects_deadline(self):
        guard = TimeoutGuard(100)  # 100ms
        # Force deadline into the past
        guard._deadline = time.monotonic() - 1
        with pytest.raises(TimeoutError):
            await guard.sleep(5.0)  # Should raise immediately

    @pytest.mark.asyncio
    async def test_sleep_completes_within_budget(self):
        guard = TimeoutGuard(5000)
        await guard.sleep(0.01)  # 10ms sleep within 5s budget — should succeed
        assert not guard.exhausted

    @pytest.mark.asyncio
    async def test_sleep_raises_immediately_if_exhausted(self):
        guard = TimeoutGuard(0)
        guard._deadline = time.monotonic() - 1
        with pytest.raises(TimeoutError):
            await guard.sleep(0.001)
