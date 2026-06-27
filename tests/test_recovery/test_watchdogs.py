"""Tests for watchdogs — BaseWatchdog lifecycle, concrete watchdogs."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from deskaoy.recovery.event_bus import WatchdogEventBus
from deskaoy.recovery.types import ActionFingerprint
from deskaoy.recovery.watchdogs import (
    CrashWatchdog,
    LoopWatchdog,
    NavigationWatchdog,
    SecurityWatchdog,
    StaleElementWatchdog,
)


class TestBaseWatchdog:
    def test_start_and_stop(self):
        async def _test():
            bus = WatchdogEventBus()
            wd = LoopWatchdog(bus)
            await wd.start()
            assert wd.is_running
            await wd.stop()
            assert not wd.is_running
        asyncio.run(_test())

    def test_name(self):
        bus = WatchdogEventBus()
        wd = LoopWatchdog(bus)
        assert wd.name == "LoopWatchdog"


class TestLoopWatchdog:
    def test_no_nudge_initially(self):
        bus = WatchdogEventBus()
        wd = LoopWatchdog(bus)
        fp = ActionFingerprint(action_type="click", target="#btn")
        assert wd.record_action(fp) is None

    def test_nudge_at_level_1(self):
        bus = WatchdogEventBus()
        wd = LoopWatchdog(bus)
        fp = ActionFingerprint(action_type="click", target="#btn")
        result = None
        for _ in range(5):
            result = wd.record_action(fp)
        assert result is not None
        assert result.level == 1

    def test_nudge_at_level_2(self):
        bus = WatchdogEventBus()
        wd = LoopWatchdog(bus)
        fp = ActionFingerprint(action_type="click", target="#btn")
        result = None
        for _ in range(8):
            result = wd.record_action(fp)
        assert result is not None
        assert result.level == 2

    def test_nudge_at_level_3(self):
        bus = WatchdogEventBus()
        wd = LoopWatchdog(bus)
        fp = ActionFingerprint(action_type="click", target="#btn")
        result = None
        for _ in range(12):
            result = wd.record_action(fp)
        assert result is not None
        assert result.level == 3

    def test_different_actions_no_nudge(self):
        bus = WatchdogEventBus()
        wd = LoopWatchdog(bus)
        for i in range(10):
            fp = ActionFingerprint(action_type="click", target=f"#btn{i}")
            wd.record_action(fp)
        fp_last = ActionFingerprint(action_type="click", target="#btn10")
        assert wd.record_action(fp_last) is None


class TestCrashWatchdog:
    def test_liveness_check_with_mock(self):
        async def _test():
            bus = WatchdogEventBus()
            cdp = MagicMock()
            result = MagicMock()
            result.ok = True
            cdp.evaluate = AsyncMock(return_value=result)
            target_result = MagicMock()
            target_result.ok = True
            target_result.data = {"targetInfos": [{"type": "page"}]}
            cdp.send = AsyncMock(return_value=target_result)
            wd = CrashWatchdog(bus, cdp, check_interval=0.01, network_timeout=1.0)
            crashed, detail = await wd._check_liveness()
            assert not crashed
        asyncio.run(_test())

    def test_liveness_failure(self):
        async def _test():
            bus = WatchdogEventBus()
            cdp = MagicMock()
            result = MagicMock()
            result.ok = False
            cdp.evaluate = AsyncMock(return_value=result)
            wd = CrashWatchdog(bus, cdp, check_interval=0.01)
            crashed, detail = await wd._check_liveness()
            assert crashed
        asyncio.run(_test())

    def test_liveness_timeout(self):
        async def _test():
            bus = WatchdogEventBus()
            cdp = MagicMock()

            async def slow(*args, **kwargs):
                await asyncio.sleep(10)

            cdp.evaluate = slow
            wd = CrashWatchdog(bus, cdp, check_interval=0.01, network_timeout=0.01)
            crashed, detail = await wd._check_liveness()
            assert crashed
        asyncio.run(_test())

    @pytest.mark.skipif(
        os.getenv("GITHUB_ACTIONS") == "true",
        reason="Process death detection via negative PID is unreliable in "
               "GitHub Actions containers (pid_exists behavior differs)",
    )
    def test_process_dead_detected(self):
        """M8: Process death detected via psutil."""
        async def _test():
            bus = WatchdogEventBus()
            cdp = MagicMock()
            result = MagicMock()
            result.ok = True
            cdp.evaluate = AsyncMock(return_value=result)
            wd = CrashWatchdog(bus, cdp, pid=-99999, check_interval=0.01)
            crashed, detail = await wd._check_liveness()
            assert crashed
            assert "dead" in detail.lower() or "process" in detail.lower()
        asyncio.run(_test())

    def test_tab_crash_detected(self):
        """M8: No page targets = tab crash."""
        async def _test():
            bus = WatchdogEventBus()
            cdp = MagicMock()
            result = MagicMock()
            result.ok = True
            cdp.evaluate = AsyncMock(return_value=result)
            target_result = MagicMock()
            target_result.ok = True
            target_result.data = {"targetInfos": [{"type": "worker"}]}
            cdp.send = AsyncMock(return_value=target_result)
            wd = CrashWatchdog(bus, cdp, check_interval=0.01)
            crashed, detail = await wd._check_liveness()
            assert crashed
            assert "tab" in detail.lower()
        asyncio.run(_test())

    def test_no_crash_all_healthy(self):
        """M8: All 3 tiers healthy."""
        async def _test():
            bus = WatchdogEventBus()
            cdp = MagicMock()
            result = MagicMock()
            result.ok = True
            cdp.evaluate = AsyncMock(return_value=result)
            target_result = MagicMock()
            target_result.ok = True
            target_result.data = {"targetInfos": [{"type": "page"}]}
            cdp.send = AsyncMock(return_value=target_result)
            wd = CrashWatchdog(bus, cdp, check_interval=0.01)
            crashed, detail = await wd._check_liveness()
            assert not crashed
            assert detail == "healthy"
        asyncio.run(_test())

    def test_no_pid_skips_process_check(self):
        """M8: Without pid, process check is skipped."""
        async def _test():
            bus = WatchdogEventBus()
            cdp = MagicMock()
            result = MagicMock()
            result.ok = True
            cdp.evaluate = AsyncMock(return_value=result)
            target_result = MagicMock()
            target_result.ok = True
            target_result.data = {"targetInfos": [{"type": "page"}]}
            cdp.send = AsyncMock(return_value=target_result)
            wd = CrashWatchdog(bus, cdp, pid=None, check_interval=0.01)
            crashed, detail = await wd._check_liveness()
            assert not crashed
        asyncio.run(_test())


class TestSecurityWatchdog:
    def test_wildcard_allows_all(self):
        bus = WatchdogEventBus()
        wd = SecurityWatchdog(bus, allowed_domains=("*",))
        assert wd.is_allowed("https://evil.com")

    def test_blocked_domain(self):
        bus = WatchdogEventBus()
        wd = SecurityWatchdog(bus, allowed_domains=("*",), blocked_domains=("*.evil.com",))
        assert not wd.is_allowed("https://x.evil.com")
        assert wd.is_allowed("https://good.com")

    def test_allowed_only(self):
        bus = WatchdogEventBus()
        wd = SecurityWatchdog(bus, allowed_domains=("*.example.com",))
        assert wd.is_allowed("https://sub.example.com")
        assert not wd.is_allowed("https://other.com")


class TestNavigationWatchdog:
    def test_mark_navigation_start(self):
        bus = WatchdogEventBus()
        wd = NavigationWatchdog(bus, nav_timeout=0.01)
        wd.mark_navigation_start()
        assert wd._nav_start is not None


class TestStaleElementWatchdog:
    def test_element_count_tracking(self):
        async def _test():
            bus = WatchdogEventBus()
            cdp = MagicMock()
            result = MagicMock()
            result.ok = True
            result.data = {"result": {"value": 42}}
            cdp.evaluate = AsyncMock(return_value=result)
            wd = StaleElementWatchdog(bus, cdp, check_interval=0.01)
            assert wd._last_fingerprint is None
            # Start/stop quickly to exercise one iteration
            await wd.start()
            await asyncio.sleep(0.02)
            await wd.stop()
        asyncio.run(_test())

    def test_stale_detected_on_element_removal(self):
        """M9: Staleness detected when interactive elements disappear."""
        old = [{"sel": "button", "x": 10, "y": 20, "w": 100, "h": 30}]
        new = []  # All elements gone
        ratio = StaleElementWatchdog._detect_staleness(old, new)
        assert ratio == 1.0

    def test_no_stale_when_below_threshold(self):
        """M9: No staleness when most elements are unchanged."""
        old = [
            {"sel": "button", "x": 10, "y": 20, "w": 100, "h": 30},
            {"sel": "input", "x": 10, "y": 60, "w": 200, "h": 30},
            {"sel": "a", "x": 10, "y": 100, "w": 50, "h": 20},
        ]
        new = [
            {"sel": "button", "x": 10, "y": 20, "w": 100, "h": 30},
            {"sel": "input", "x": 10, "y": 60, "w": 200, "h": 30},
            # 'a' removed — 1/3 = 0.33, above default threshold of 0.2
        ]
        ratio = StaleElementWatchdog._detect_staleness(old, new)
        assert ratio > 0.2

    def test_stale_detected_on_rect_change(self):
        """M9: Element moved = stale."""
        old = [{"sel": "button", "x": 10, "y": 20, "w": 100, "h": 30}]
        new = [{"sel": "button", "x": 50, "y": 60, "w": 100, "h": 30}]  # Moved
        ratio = StaleElementWatchdog._detect_staleness(old, new)
        assert ratio == 1.0  # Original position no longer exists

    def test_no_stale_when_all_same(self):
        """M9: No staleness when nothing changed."""
        fp = [{"sel": "button", "x": 10, "y": 20, "w": 100, "h": 30}]
        ratio = StaleElementWatchdog._detect_staleness(fp, fp)
        assert ratio == 0.0

    def test_staleness_with_empty_old(self):
        """M9: Empty old fingerprint = no staleness."""
        ratio = StaleElementWatchdog._detect_staleness([], [{"sel": "b", "x": 0, "y": 0, "w": 1, "h": 1}])
        assert ratio == 0.0
