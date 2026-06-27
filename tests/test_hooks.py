"""Tests for deskaoy.hooks — G8 Hook System."""

from __future__ import annotations

import pytest

from deskaoy.hooks import HookContext, HookName, HookRegistry

# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegistration:

    def test_on_registers_callback(self):
        reg = HookRegistry()
        calls = []
        async def cb(ctx): calls.append(ctx.command)
        reg.on(HookName.ON_STEP_COMPLETE, cb)
        assert reg.registered == {"on_step_complete": 1}

    def test_off_removes_callback(self):
        reg = HookRegistry()
        async def cb(ctx): pass
        reg.on(HookName.ON_STEP_START, cb)
        reg.off(HookName.ON_STEP_START, cb)
        assert reg.registered == {}

    def test_multiple_callbacks_same_hook(self):
        reg = HookRegistry()
        async def a(ctx): pass
        async def b(ctx): pass
        reg.on(HookName.ON_STEP_COMPLETE, a)
        reg.on(HookName.ON_STEP_COMPLETE, b)
        assert reg.registered == {"on_step_complete": 2}

    def test_off_nonexistent_is_noop(self):
        reg = HookRegistry()
        async def cb(ctx): pass
        reg.off(HookName.ON_STARTUP, cb)  # should not raise


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------

class TestEmission:

    @pytest.mark.asyncio
    async def test_emit_calls_callbacks(self):
        reg = HookRegistry()
        results = []
        async def cb(ctx):
            results.append(ctx.command)
        reg.on(HookName.ON_STEP_COMPLETE, cb)
        await reg.emit(HookName.ON_STEP_COMPLETE, HookContext(command="click"))
        assert results == ["click"]

    @pytest.mark.asyncio
    async def test_emit_empty_is_noop(self):
        reg = HookRegistry()
        await reg.emit(HookName.ON_STARTUP, HookContext())  # no callbacks, no error

    @pytest.mark.asyncio
    async def test_failing_hook_does_not_block(self):
        """G8 requirement: a failing hook never blocks the caller."""
        reg = HookRegistry()
        results = []

        async def bad(ctx):
            raise RuntimeError("boom")

        async def good(ctx):
            results.append(ctx.command)

        reg.on(HookName.ON_STEP_ERROR, bad)
        reg.on(HookName.ON_STEP_ERROR, good)

        await reg.emit(HookName.ON_STEP_ERROR, HookContext(command="fail"))
        assert results == ["fail"]  # good still ran despite bad failing first

    @pytest.mark.asyncio
    async def test_context_duration(self):
        ctx = HookContext(started_at=1.0, finished_at=2.5)
        assert ctx.duration_ms == 1500.0

    @pytest.mark.asyncio
    async def test_context_duration_unset(self):
        ctx = HookContext()
        assert ctx.duration_ms == 0.0


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------

class TestClear:

    def test_clear_removes_all(self):
        reg = HookRegistry()
        async def cb(ctx): pass
        reg.on(HookName.ON_STEP_START, cb)
        reg.on(HookName.ON_STEP_COMPLETE, cb)
        reg.clear()
        assert reg.registered == {}
