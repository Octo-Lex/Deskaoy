"""Tests for SnapshotStore metrics (BATCH-31)."""
from __future__ import annotations

from pathlib import Path

import pytest

from deskaoy.cascade.snapshot_store import SnapshotMetrics, SnapshotStore


@pytest.fixture
def store(tmp_path: Path) -> SnapshotStore:
    """Create a SnapshotStore with a temp directory."""
    return SnapshotStore(snapshot_dir=tmp_path, max_snapshots=5)


class TestSnapshotMetrics:
    """Test SnapshotMetrics dataclass."""

    def test_default_values(self):
        m = SnapshotMetrics()
        assert m.hits == 0
        assert m.misses == 0
        assert m.evictions == 0
        assert m.total_size_bytes == 0
        assert m.count == 0


class TestGetMetrics:
    """Test SnapshotStore.get_metrics()."""

    @pytest.mark.asyncio
    async def test_empty_store(self, store: SnapshotStore):
        metrics = await store.get_metrics()
        assert metrics.count == 0
        assert metrics.total_size_bytes == 0
        assert metrics.hits == 0
        assert metrics.misses == 0
        assert metrics.evictions == 0

    @pytest.mark.asyncio
    async def test_count_after_create(self, store: SnapshotStore):
        await store.create([], metadata={"application": "test"})
        metrics = await store.get_metrics()
        assert metrics.count == 1

    @pytest.mark.asyncio
    async def test_hits_on_get(self, store: SnapshotStore):
        sid = await store.create([], metadata={"application": "test"})
        await store.get(sid)  # hit
        await store.get(sid)  # hit
        metrics = await store.get_metrics()
        assert metrics.hits == 2

    @pytest.mark.asyncio
    async def test_misses_on_missing(self, store: SnapshotStore):
        await store.get("nonexistent_id")  # miss
        await store.get("another_missing")  # miss
        metrics = await store.get_metrics()
        assert metrics.misses == 2

    @pytest.mark.asyncio
    async def test_evictions_tracked(self, tmp_path: Path):
        """Store with max_snapshots=2, create 3 → 1 eviction."""
        small_store = SnapshotStore(snapshot_dir=tmp_path / "evict", max_snapshots=2)
        await small_store.create([], metadata={"application": "a"})
        await small_store.create([], metadata={"application": "b"})
        await small_store.create([], metadata={"application": "c"})
        metrics = await small_store.get_metrics()
        assert metrics.evictions == 1
        assert metrics.count == 2

    @pytest.mark.asyncio
    async def test_total_size_after_create_with_screenshot(self, store: SnapshotStore):
        screenshot = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        await store.create([], screenshot_bytes=screenshot, metadata={"application": "test"})
        metrics = await store.get_metrics()
        assert metrics.total_size_bytes > 0


class TestResetMetrics:
    """Test SnapshotStore.reset_metrics()."""

    @pytest.mark.asyncio
    async def test_reset_clears_counters(self, store: SnapshotStore):
        sid = await store.create([], metadata={"application": "test"})
        await store.get(sid)  # hit
        await store.get("missing")  # miss

        store.reset_metrics()
        metrics = await store.get_metrics()
        assert metrics.hits == 0
        assert metrics.misses == 0
        assert metrics.evictions == 0
        # count is computed from disk, not reset
        assert metrics.count >= 1
