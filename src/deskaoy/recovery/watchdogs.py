"""Watchdogs — BaseWatchdog ABC and 5 concrete watchdog implementations."""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from deskaoy.agent.loop_detector import ActionLoopDetector
from deskaoy.recovery.event_bus import WatchdogEventBus
from deskaoy.recovery.types import (
    ActionFingerprint,
    NudgePayload,
    WatchdogEvent,
    WatchdogEventData,
)

logger = logging.getLogger(__name__)


class BaseWatchdog(ABC):
    LISTENS_TO: list[WatchdogEvent] = []
    EMITS: list[WatchdogEvent] = []

    def __init__(self, event_bus: WatchdogEventBus) -> None:
        self._event_bus = event_bus
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._monitoring_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _emit(
        self, event_type: WatchdogEvent, detail: str,
        severity: str = "warning", data: dict | None = None,
    ) -> None:
        event = WatchdogEventData(
            event_type=event_type, source=self.name,
            detail=detail, severity=severity, data=data,
        )
        await self._event_bus.emit(event)

    @abstractmethod
    async def _monitoring_loop(self) -> None:
        ...

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def name(self) -> str:
        return type(self).__name__


class CrashWatchdog(BaseWatchdog):
    """M8: 3-tier liveness check — process, CDP, tab target."""
    LISTENS_TO: list[WatchdogEvent] = []
    EMITS = [WatchdogEvent.CRASH_DETECTED, WatchdogEvent.SESSION_STALE]

    def __init__(
        self,
        event_bus: WatchdogEventBus,
        cdp: Any,
        pid: int | None = None,
        check_interval: float = 5.0,
        network_timeout: float = 10.0,
    ) -> None:
        super().__init__(event_bus)
        self._cdp = cdp
        self._pid = pid
        self._check_interval = check_interval
        self._network_timeout = network_timeout

    async def _monitoring_loop(self) -> None:
        while self._running:
            try:
                crashed, detail = await self._check_liveness()
                if crashed:
                    await self._emit(
                        WatchdogEvent.CRASH_DETECTED,
                        f"Browser liveness check failed: {detail}",
                        severity="critical",
                    )
                    return
            except Exception as exc:
                await self._emit(
                    WatchdogEvent.SESSION_STALE,
                    f"CDP session unreachable: {exc}",
                    severity="critical",
                )
                return
            await asyncio.sleep(self._check_interval)

    async def _check_liveness(self) -> tuple[bool, str]:
        """3-tier liveness: process → CDP → target. Returns (crashed, detail)."""
        # Tier 1: Process check (instant, no CDP needed)
        if self._pid is not None:
            proc_ok, proc_detail = self._check_process()
            if not proc_ok:
                return True, proc_detail

        # Tier 2: CDP ping (catches frozen renderer)
        cdp_ok, cdp_detail = await self._check_cdp()
        if not cdp_ok:
            return True, cdp_detail

        # Tier 3: Target check (catches tab-level crashes)
        target_ok, target_detail = await self._check_target()
        if not target_ok:
            return True, target_detail

        return False, "healthy"

    def _check_process(self) -> tuple[bool, str]:
        """Check if browser process is still alive."""
        try:
            import psutil
            if not psutil.pid_exists(self._pid):
                return False, f"process {self._pid} dead"
            return True, ""
        except ImportError:
            # psutil not available — skip this tier
            return True, ""

    async def _check_cdp(self) -> tuple[bool, str]:
        """CDP ping: evaluate 1+1 to check renderer responsiveness."""
        try:
            result = await asyncio.wait_for(
                self._cdp.evaluate("1+1"), timeout=self._network_timeout,
            )
            if not result.ok:
                return False, "CDP evaluate returned not ok"
            return True, ""
        except TimeoutError:
            return False, "CDP ping timed out (renderer may be frozen)"
        except Exception as exc:
            return False, f"CDP error: {exc}"

    async def _check_target(self) -> tuple[bool, str]:
        """Target check: verify at least one page target exists."""
        try:
            result = await asyncio.wait_for(
                self._cdp.send("Target.getTargets", {}),
                timeout=self._network_timeout,
            )
            if result.ok and result.data:
                targets = result.data.get("targetInfos", [])
                pages = [t for t in targets if t.get("type") == "page"]
                if not pages:
                    return False, "no page targets found (tab crashed)"
            return True, ""
        except TimeoutError:
            # Target check timeout is not necessarily fatal — CDP may still work
            return True, ""
        except Exception:
            return True, ""


class LoopWatchdog(BaseWatchdog):
    LISTENS_TO: list[WatchdogEvent] = []
    EMITS = [WatchdogEvent.LOOP_DETECTED, WatchdogEvent.NUDGE_INJECT]

    def __init__(self, event_bus: WatchdogEventBus, window_size: int = 20) -> None:
        super().__init__(event_bus)
        self._detector = ActionLoopDetector(window_size=window_size)

    def record_action(self, fingerprint: ActionFingerprint) -> NudgePayload | None:
        action_dict = {
            "action_type": fingerprint.action_type,
            "target": fingerprint.target,
            "value": fingerprint.value,
        }
        nudge = self._detector.record_and_check(action_dict)
        if nudge is None:
            return None
        return NudgePayload(
            level=nudge.level,
            message=nudge.message,
            repetition_count=nudge.repetition_count,
            action_hash=fingerprint.hash,
        )

    async def _monitoring_loop(self) -> None:
        while self._running:
            await asyncio.sleep(1.0)


class NavigationWatchdog(BaseWatchdog):
    EMITS = [WatchdogEvent.NAVIGATION_TIMEOUT]

    def __init__(
        self,
        event_bus: WatchdogEventBus,
        cdp: Any = None,
        nav_timeout: float = 30.0,
    ) -> None:
        super().__init__(event_bus)
        self._cdp = cdp
        self._nav_timeout = nav_timeout
        self._nav_start: float | None = None

    def mark_navigation_start(self) -> None:
        self._nav_start = time.monotonic()

    async def _monitoring_loop(self) -> None:
        while self._running:
            if self._nav_start is not None:
                elapsed = time.monotonic() - self._nav_start
                if elapsed > self._nav_timeout:
                    await self._emit(
                        WatchdogEvent.NAVIGATION_TIMEOUT,
                        f"Navigation exceeded {self._nav_timeout}s",
                        severity="warning",
                    )
                    self._nav_start = None
            await asyncio.sleep(1.0)


class StaleElementWatchdog(BaseWatchdog):
    """M9: Tracks interactive elements instead of total DOM count.

    Compares fingerprints of interactive elements (buttons, inputs, links)
    to detect when the page has changed enough that cached selectors
    may be stale.
    """
    EMITS = [WatchdogEvent.STALE_ELEMENT]

    # JS that extracts interactive element fingerprints: [selector, rect]
    _FINGERPRINT_JS = """
    (function() {
        var els = document.querySelectorAll(
            'button, input, select, textarea, a[href], [role="button"], [role="link"], [onclick]'
        );
        var fp = [];
        for (var i = 0; i < els.length; i++) {
            var r = els[i].getBoundingClientRect();
            if (r.width > 0 && r.height > 0) {
                fp.push({
                    sel: els[i].id ? '#' + els[i].id : els[i].tagName.toLowerCase(),
                    x: Math.round(r.x), y: Math.round(r.y),
                    w: Math.round(r.width), h: Math.round(r.height),
                });
            }
        }
        return JSON.stringify(fp);
    })()
    """

    def __init__(
        self,
        event_bus: WatchdogEventBus,
        cdp: Any = None,
        check_interval: float = 5.0,
        staleness_threshold: float = 0.2,
    ) -> None:
        super().__init__(event_bus)
        self._cdp = cdp
        self._check_interval = check_interval
        self._staleness_threshold = staleness_threshold
        self._last_fingerprint: list[dict] | None = None

    async def _monitoring_loop(self) -> None:
        while self._running:
            if self._cdp:
                try:
                    current = await self._capture_interactive_elements()
                    if current is not None:
                        if self._last_fingerprint is not None:
                            stale_ratio = self._detect_staleness(
                                self._last_fingerprint, current,
                            )
                            if stale_ratio > self._staleness_threshold:
                                await self._emit(
                                    WatchdogEvent.STALE_ELEMENT,
                                    f"Interactive elements changed: {stale_ratio:.0%} stale",
                                )
                        self._last_fingerprint = current
                except Exception:
                    pass
            await asyncio.sleep(self._check_interval)

    async def _capture_interactive_elements(self) -> list[dict] | None:
        """Get current interactive element fingerprints from the page."""
        if self._cdp is None:
            return None
        result = await self._cdp.evaluate(self._FINGERPRINT_JS)
        if not result.ok or not result.data:
            return None
        raw = result.data.get("result", {}).get("value")
        if not raw:
            return None
        import json
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _detect_staleness(
        old: list[dict], new: list[dict],
    ) -> float:
        """Compute ratio of elements that disappeared or moved significantly."""
        if not old:
            return 0.0
        new_set = {
            (e["sel"], e["x"], e["y"], e["w"], e["h"]) for e in new
        }
        missing = 0
        for e in old:
            key = (e["sel"], e["x"], e["y"], e["w"], e["h"])
            if key not in new_set:
                missing += 1
        return missing / len(old)


class SecurityWatchdog(BaseWatchdog):
    EMITS = [WatchdogEvent.SECURITY_VIOLATION]

    def __init__(
        self,
        event_bus: WatchdogEventBus,
        allowed_domains: tuple[str, ...] = ("*",),
        blocked_domains: tuple[str, ...] = (),
        page: Any = None,
        check_interval: float = 5.0,
    ) -> None:
        super().__init__(event_bus)
        self._allowed = allowed_domains
        self._blocked = blocked_domains
        self._page = page
        self._check_interval = check_interval

    def is_allowed(self, url: str) -> bool:
        if "*" in self._allowed:
            pass
        else:
            matched = any(fnmatch.fnmatch(url, p) for p in self._allowed)
            if not matched:
                return False

        if self._blocked:
            matched = any(fnmatch.fnmatch(url, p) for p in self._blocked)
            if matched:
                return False
        return True

    async def _monitoring_loop(self) -> None:
        while self._running:
            if self._page:
                url = getattr(self._page, "url", "")
                if url and not self.is_allowed(url):
                    await self._emit(
                        WatchdogEvent.SECURITY_VIOLATION,
                        f"Blocked domain: {url}",
                        severity="critical",
                    )
            await asyncio.sleep(self._check_interval)
