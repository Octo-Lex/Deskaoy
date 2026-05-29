"""Plugin lifecycle hooks for cross-cutting concerns.

Provides 9 hook points that fire at key moments during agent execution.
Hooks are async callables that receive a :class:`HookContext`.  A failing
hook **never** blocks the caller — errors are logged and swallowed.

Usage::

    from deskaoy.hooks import HookName, hooks

    async def log_step(ctx):
        print(f"Step {ctx.extra['step_number']}: {ctx.command}")

    hooks.on(HookName.ON_STEP_COMPLETE, log_step)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hook names
# ---------------------------------------------------------------------------

class HookName(StrEnum):
    """Canonical lifecycle points."""
    ON_STARTUP = "on_startup"
    ON_BEFORE_EXECUTE = "on_before_execute"
    ON_AFTER_EXECUTE = "on_after_execute"
    ON_STEP_START = "on_step_start"
    ON_STEP_COMPLETE = "on_step_complete"
    ON_STEP_ERROR = "on_step_error"
    ON_TIER_ATTEMPT = "on_tier_attempt"
    ON_MEMORY_RECORD = "on_memory_record"
    ON_MEMORY_RECALL = "on_memory_recall"


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

@dataclass
class HookContext:
    """Bag of data passed to every hook callback."""
    command: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    started_at: float = 0.0
    finished_at: float = 0.0
    error: Exception | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        if self.finished_at and self.started_at:
            return (self.finished_at - self.started_at) * 1000
        return 0.0


# ---------------------------------------------------------------------------
# Callback type
# ---------------------------------------------------------------------------

HookFn = Callable[[HookContext], Awaitable[None]]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class HookRegistry:
    """Global singleton-like registry for lifecycle hooks."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookFn]] = {}

    def on(self, name: HookName, fn: HookFn) -> None:
        """Register *fn* to be called when hook *name* fires."""
        self._hooks.setdefault(str(name), []).append(fn)

    def off(self, name: HookName, fn: HookFn) -> None:
        """Unregister *fn* from hook *name*."""
        bucket = self._hooks.get(str(name), [])
        if fn in bucket:
            bucket.remove(fn)
        # Clean up empty buckets
        if not bucket:
            self._hooks.pop(str(name), None)

    async def emit(self, name: HookName, ctx: HookContext) -> None:
        """Fire all callbacks registered for *name*. Errors are isolated."""
        for fn in self._hooks.get(str(name), []):
            try:
                await fn(ctx)
            except Exception:
                logger.warning("Hook %s callback %s failed", name, fn, exc_info=True)

    def clear(self) -> None:
        """Remove all registered hooks (useful for tests)."""
        self._hooks.clear()

    @property
    def registered(self) -> dict[str, int]:
        """Return a summary of how many hooks are registered per name."""
        return {k: len(v) for k, v in self._hooks.items()}


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

hooks = HookRegistry()
