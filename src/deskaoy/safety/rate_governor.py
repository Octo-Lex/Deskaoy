"""ActionRateGovernor — token-bucket rate limiter per action type.

Prevents runaway agent loops from flooding the desktop with actions.
Each action type has its own sliding-window counter with a cooldown
period after the limit is hit.

Wire into DesktopAgent._execute_single_action() before dispatch.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class RateLimit:
    """Rate limit configuration for a single action type."""

    max_actions: int          # max actions in window
    window_seconds: float     # sliding window duration
    cooldown_seconds: float   # mandatory pause after limit hit


# Sensible defaults based on expected desktop action frequencies
DEFAULT_LIMITS: dict[str, RateLimit] = {
    "click":      RateLimit(max_actions=30, window_seconds=10.0, cooldown_seconds=1.0),
    "type_text":  RateLimit(max_actions=20, window_seconds=10.0, cooldown_seconds=0.5),
    "fill":       RateLimit(max_actions=20, window_seconds=10.0, cooldown_seconds=0.5),
    "key_press":  RateLimit(max_actions=40, window_seconds=10.0, cooldown_seconds=0.2),
    "scroll":     RateLimit(max_actions=60, window_seconds=10.0, cooldown_seconds=0.1),
    "screenshot": RateLimit(max_actions=10, window_seconds=10.0, cooldown_seconds=0.5),
    "snapshot":   RateLimit(max_actions=10, window_seconds=10.0, cooldown_seconds=0.5),
    "navigate":   RateLimit(max_actions=10, window_seconds=10.0, cooldown_seconds=1.0),
    "automate":   RateLimit(max_actions=5,  window_seconds=60.0, cooldown_seconds=5.0),
    "default":    RateLimit(max_actions=20, window_seconds=10.0, cooldown_seconds=1.0),
}


class ActionRateGovernor:
    """Token-bucket rate limiter per action type.

    Uses a sliding-window counter: each action type tracks timestamps
    of recent invocations. If the count within the window exceeds
    *max_actions*, further actions are blocked until the cooldown
    period expires.

    Thread-safe via a lock (agent loop is async but we may have
    concurrent surface adapters).
    """

    def __init__(self, limits: dict[str, RateLimit] | None = None) -> None:
        self._limits = limits or DEFAULT_LIMITS
        self._timestamps: dict[str, list[float]] = defaultdict(list)
        self._cooldown_until: dict[str, float] = {}  # action → unblock timestamp
        self._lock = threading.Lock()

    def _get_limit(self, action: str) -> RateLimit:
        """Get the rate limit for an action, falling back to default."""
        return self._limits.get(action, self._limits.get("default", DEFAULT_LIMITS["default"]))

    def _prune(self, action: str, now: float) -> list[float]:
        """Remove timestamps outside the sliding window."""
        limit = self._get_limit(action)
        cutoff = now - limit.window_seconds
        ts = [t for t in self._timestamps[action] if t > cutoff]
        self._timestamps[action] = ts
        return ts

    def check(self, action: str) -> bool:
        """Check if an action can proceed without exceeding the rate limit.

        Returns True if the action is allowed, False if rate-limited.
        """
        with self._lock:
            now = time.monotonic()
            # Check cooldown
            cooldown_end = self._cooldown_until.get(action, 0.0)
            if now < cooldown_end:
                return False
            # Check window count
            ts = self._prune(action, now)
            limit = self._get_limit(action)
            return len(ts) < limit.max_actions

    def record(self, action: str) -> None:
        """Record that an action was taken.

        If this recording causes the limit to be exceeded, the cooldown
        timer is started automatically.
        """
        with self._lock:
            now = time.monotonic()
            self._timestamps[action].append(now)
            # Check if we just hit the limit → start cooldown
            ts = self._prune(action, now)
            limit = self._get_limit(action)
            if len(ts) >= limit.max_actions:
                self._cooldown_until[action] = now + limit.cooldown_seconds

    def wait_if_needed(self, action: str) -> float:
        """Return the number of seconds the caller should wait.

        Returns 0.0 if the action can proceed immediately.
        Returns >0 if rate-limited, indicating how long to wait.
        """
        with self._lock:
            now = time.monotonic()
            # Check cooldown
            cooldown_end = self._cooldown_until.get(action, 0.0)
            if now < cooldown_end:
                return cooldown_end - now
            # Check window count
            ts = self._prune(action, now)
            limit = self._get_limit(action)
            if len(ts) >= limit.max_actions:
                # Earliest timestamp in window determines when a slot opens
                oldest = min(ts) if ts else now
                wait = max(0.0, (oldest + limit.window_seconds) - now)
                return wait
            return 0.0

    def reset(self, action: str | None = None) -> None:
        """Reset rate limit counters.

        If *action* is provided, resets only that action type.
        Otherwise, resets all counters.
        """
        with self._lock:
            if action is not None:
                self._timestamps.pop(action, None)
                self._cooldown_until.pop(action, None)
            else:
                self._timestamps.clear()
                self._cooldown_until.clear()

    @property
    def stats(self) -> dict[str, dict]:
        """Current state per action type.

        Returns a dict mapping action names to their current count,
        limit, and cooldown remaining seconds.
        """
        with self._lock:
            now = time.monotonic()
            result: dict[str, dict] = {}
            for action in sorted(set(list(self._timestamps.keys()) + list(self._cooldown_until.keys()))):
                ts = self._prune(action, now)
                limit = self._get_limit(action)
                cooldown_end = self._cooldown_until.get(action, 0.0)
                cooldown_remaining = max(0.0, cooldown_end - now)
                result[action] = {
                    "count": len(ts),
                    "max": limit.max_actions,
                    "window_seconds": limit.window_seconds,
                    "cooldown_remaining": cooldown_remaining,
                    "limited": len(ts) >= limit.max_actions or cooldown_remaining > 0,
                }
            return result
