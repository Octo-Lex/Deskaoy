"""Integration tests — checkpoint persistence and event bus with real data."""

import asyncio

import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_checkpoint_round_trip(real_browser, tmp_path):
    """H6 fix: checkpoint save/load with real page state."""
    from tests.integration.conftest import _test_html_uri
    from deskaoy.recovery.checkpoint import CheckpointManager

    session, page, cdp = real_browser
    await page.goto(_test_html_uri())

    mgr = CheckpointManager(tmp_path)
    await mgr.initialize()

    title = await page.title()
    scroll_y = await page.raw_page.evaluate("Math.round(window.scrollY)")

    cp = await mgr.create_checkpoint(
        message="pre-click checkpoint",
        url=page.url,
        title=title,
        scroll_y=scroll_y,
        action_history=[{"action": "navigate", "url": page.url}],
    )
    assert cp is not None
    assert cp.checkpoint_id

    # Load it back
    data = mgr.load_checkpoint_data(cp.checkpoint_id)
    assert data is not None
    assert data["url"] == page.url
    assert data["title"] == "Test Page"
    assert data["scroll_y"] == 0
    assert len(data["actions"]) == 1

    # Rollback returns True
    assert await mgr.rollback(cp.checkpoint_id) is True

    # Nonexistent checkpoint returns False
    assert await mgr.rollback("no-such-id") is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_checkpoint_persists_across_instances(real_browser, tmp_path):
    """H6 fix: checkpoints survive manager restart."""
    from tests.integration.conftest import _test_html_uri
    from deskaoy.recovery.checkpoint import CheckpointManager

    session, page, cdp = real_browser
    await page.goto(_test_html_uri())

    # Create checkpoint with first manager
    mgr1 = CheckpointManager(tmp_path)
    await mgr1.initialize()
    cp = await mgr1.create_checkpoint(
        message="persistent checkpoint",
        url=page.url,
    )

    # Second manager loads from same dir
    mgr2 = CheckpointManager(tmp_path)
    await mgr2.initialize()

    checkpoints = mgr2.list_checkpoints()
    assert len(checkpoints) >= 1
    assert any(c.checkpoint_id == cp.checkpoint_id for c in checkpoints)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_event_bus_history_cap():
    """M11 fix: event bus history is capped to max_history."""
    from deskaoy.recovery.event_bus import WatchdogEventBus
    from deskaoy.recovery.types import WatchdogEvent, WatchdogEventData

    bus = WatchdogEventBus(max_history=5)

    for i in range(10):
        await bus.emit(WatchdogEventData(
            event_type=WatchdogEvent.RECOVERY_STARTED,
            source="test",
            detail=f"event {i}",
        ))

    assert len(bus._history) == 5
    events = bus.drain()
    # Newest events preserved
    assert events[-1].detail == "event 9"
    assert events[0].detail == "event 5"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_event_bus_subscribe_and_drain():
    """Event bus delivers events to subscribers."""
    from deskaoy.recovery.event_bus import WatchdogEventBus
    from deskaoy.recovery.types import WatchdogEvent, WatchdogEventData

    bus = WatchdogEventBus()
    received = []

    async def handler(event):
        received.append(event)

    bus.subscribe([WatchdogEvent.RECOVERY_STARTED], handler)

    await bus.emit(WatchdogEventData(
        event_type=WatchdogEvent.RECOVERY_STARTED,
        source="test",
        detail="test event",
    ))

    assert len(received) == 1
    assert received[0].detail == "test event"
    assert len(bus.drain()) == 1
