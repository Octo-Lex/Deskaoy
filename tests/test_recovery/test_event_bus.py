"""Tests for WatchdogEventBus."""

import asyncio

from deskaoy.recovery.event_bus import WatchdogEventBus
from deskaoy.recovery.types import WatchdogEvent, WatchdogEventData


def _event(event_type: WatchdogEvent, detail: str = "test") -> WatchdogEventData:
    return WatchdogEventData(event_type=event_type, source="test", detail=detail)


class TestWatchdogEventBus:
    def test_emit_and_listen(self):
        async def _test():
            bus = WatchdogEventBus(max_queue_size=10)
            q = bus.listen(WatchdogEvent.CRASH_DETECTED)
            await bus.emit(_event(WatchdogEvent.CRASH_DETECTED, "crash!"))
            event = q.get_nowait()
            assert event.detail == "crash!"
            assert event.event_type == WatchdogEvent.CRASH_DETECTED
        asyncio.run(_test())

    def test_filtered_listen(self):
        async def _test():
            bus = WatchdogEventBus()
            q_crash = bus.listen(WatchdogEvent.CRASH_DETECTED)
            q_recovery = bus.listen(WatchdogEvent.RECOVERY_STARTED)
            await bus.emit(_event(WatchdogEvent.CRASH_DETECTED))
            assert not q_crash.empty()
            assert q_recovery.empty()
        asyncio.run(_test())

    def test_drop_oldest_on_overflow(self):
        async def _test():
            bus = WatchdogEventBus(max_queue_size=3)
            q = bus.listen(WatchdogEvent.CRASH_DETECTED)
            for i in range(5):
                await bus.emit(_event(WatchdogEvent.CRASH_DETECTED, f"event-{i}"))
            assert q.qsize() <= 3
        asyncio.run(_test())

    def test_subscribe_handler(self):
        async def _test():
            bus = WatchdogEventBus()
            received = []
            bus.subscribe([WatchdogEvent.CRASH_DETECTED], lambda e: received.append(e))
            await bus.emit(_event(WatchdogEvent.CRASH_DETECTED, "handled"))
            assert len(received) == 1
            assert received[0].detail == "handled"
        asyncio.run(_test())

    def test_subscribe_async_handler(self):
        async def _test():
            bus = WatchdogEventBus()
            received = []

            async def handler(e):
                received.append(e)

            bus.subscribe([WatchdogEvent.RECOVERY_COMPLETED], handler)
            await bus.emit(_event(WatchdogEvent.RECOVERY_COMPLETED, "done"))
            assert len(received) == 1
        asyncio.run(_test())

    def test_drain(self):
        async def _test():
            bus = WatchdogEventBus()
            await bus.emit(_event(WatchdogEvent.CRASH_DETECTED, "a"))
            await bus.emit(_event(WatchdogEvent.RECOVERY_STARTED, "b"))
            events = bus.drain()
            assert len(events) == 2
        asyncio.run(_test())

    def test_clear(self):
        async def _test():
            bus = WatchdogEventBus()
            q = bus.listen(WatchdogEvent.CRASH_DETECTED)
            await bus.emit(_event(WatchdogEvent.CRASH_DETECTED))
            bus.clear()
            assert q.empty()
            assert bus.drain() == []
        asyncio.run(_test())

    def test_unmatched_event_ignored(self):
        async def _test():
            bus = WatchdogEventBus()
            q = bus.listen(WatchdogEvent.CRASH_DETECTED)
            await bus.emit(_event(WatchdogEvent.RECOVERY_STARTED))
            assert q.empty()
        asyncio.run(_test())


class TestM11UnboundedHistory:
    def test_history_capped_at_max(self):
        """M11: Event history should be capped at max_history."""
        async def _test():
            bus = WatchdogEventBus(max_history=10)
            for i in range(20):
                await bus.emit(_event(WatchdogEvent.RECOVERY_STARTED, f"event {i}"))
            assert len(bus._history) == 10
        asyncio.run(_test())

    def test_history_keeps_recent_events(self):
        """M11: When capped, most recent events are preserved."""
        async def _test():
            bus = WatchdogEventBus(max_history=5)
            for i in range(10):
                await bus.emit(_event(WatchdogEvent.RECOVERY_STARTED, f"event {i}"))
            events = bus.drain()
            assert events[0].detail == "event 5"  # oldest kept
            assert events[-1].detail == "event 9"  # newest
        asyncio.run(_test())

    def test_default_max_history(self):
        """M11: Default max_history should be 1000."""
        bus = WatchdogEventBus()
        assert bus._max_history == 1000
