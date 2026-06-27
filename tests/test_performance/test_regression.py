"""Performance regression tests (BATCH-31).

All tests use mocked adapters to ensure deterministic, fast execution.
Latency budgets:
  - Screenshot capture < 500ms
  - Observation pipeline (quick preset) < 1s
  - Snapshot create+read < 100ms
  - Health check < 200ms
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deskaoy.cascade.snapshot_store import SnapshotStore
from deskaoy.observation import ObservationConfig
from deskaoy.observation_pipeline import ObservationPipeline
from deskaoy.safety.health import HealthCheck

# ── Mock Adapters ──────────────────────────────────────────────────────

class MockSurfaceAdapter:
    """Mock surface adapter that returns deterministic results."""

    async def screenshot(self) -> bytes:
        """Simulate screenshot capture — deterministic delay."""
        await asyncio.sleep(0.001)  # 1ms simulated capture
        return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    async def current_title(self) -> str:
        return "Test Window"


class MockUIAWalker:
    """Mock UIA walker returning empty tree."""

    def walk(self):
        return []

    def get_focused_element(self):
        return None


# ── Screenshot Latency ─────────────────────────────────────────────────

class TestScreenshotLatency:
    """Screenshot capture must complete within 500ms."""

    @pytest.mark.asyncio
    async def test_mocked_screenshot_under_500ms(self):
        adapter = MockSurfaceAdapter()
        start = time.monotonic()
        screenshot = await adapter.screenshot()
        elapsed_ms = (time.monotonic() - start) * 1000
        assert len(screenshot) > 0
        assert elapsed_ms < 500.0, f"Screenshot took {elapsed_ms:.1f}ms (limit: 500ms)"

    @pytest.mark.asyncio
    async def test_ten_consecutive_screenshots_under_500ms_each(self):
        adapter = MockSurfaceAdapter()
        for i in range(10):
            start = time.monotonic()
            await adapter.screenshot()
            elapsed_ms = (time.monotonic() - start) * 1000
            assert elapsed_ms < 500.0, f"Screenshot {i} took {elapsed_ms:.1f}ms"


# ── Observation Pipeline Latency ───────────────────────────────────────

class TestObservationPipelineLatency:
    """Observation pipeline (quick preset) must complete within 1s."""

    @pytest.mark.asyncio
    async def test_quick_preset_under_1s(self):
        adapter = MockSurfaceAdapter()
        walker = MockUIAWalker()
        pipeline = ObservationPipeline(adapter=adapter, walker=walker)

        start = time.monotonic()
        result = await pipeline.observe(ObservationConfig(preset="quick"))
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 1000.0, f"Quick observe took {elapsed_ms:.1f}ms (limit: 1000ms)"
        assert "capture" in result.steps_completed
        assert "ax_walk" in result.steps_completed


# ── Snapshot Create+Read Latency ───────────────────────────────────────

class TestSnapshotCreateReadLatency:
    """Snapshot create + read must complete within 100ms."""

    @pytest.mark.asyncio
    async def test_create_read_under_100ms(self, tmp_path: Path):
        store = SnapshotStore(snapshot_dir=tmp_path)

        start = time.monotonic()
        sid = await store.create(
            [{"role": "button", "name": "OK"}],
            metadata={"application": "test"},
        )
        record = await store.get(sid)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert record is not None
        assert elapsed_ms < 100.0, f"Create+read took {elapsed_ms:.1f}ms (limit: 100ms)"

    @pytest.mark.asyncio
    async def test_create_with_screenshot_under_100ms(self, tmp_path: Path):
        store = SnapshotStore(snapshot_dir=tmp_path)
        screenshot = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

        start = time.monotonic()
        sid = await store.create([], screenshot_bytes=screenshot)
        record = await store.get(sid)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert record is not None
        assert elapsed_ms < 100.0, f"Create+read with screenshot took {elapsed_ms:.1f}ms"


# ── Health Check Latency ───────────────────────────────────────────────

class TestHealthCheckLatency:
    """Health check must complete within 200ms."""

    @pytest.mark.asyncio
    async def test_health_check_under_200ms(self):
        health = HealthCheck(agent=MagicMock())
        start = time.monotonic()
        result = await health.check()
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 200.0, f"Health check took {elapsed_ms:.1f}ms (limit: 200ms)"
        assert hasattr(result, "healthy") or hasattr(result, "status")
