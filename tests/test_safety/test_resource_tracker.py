"""Tests for ResourceTracker (v0.16.0 — UI-TARS pattern)."""

from __future__ import annotations

import time

import pytest

from deskaoy.safety.resource_tracker import ResourceTracker, TrackedResource


class TestResourceTracker:
    def test_track_adds_resource(self):
        tracker = ResourceTracker()
        tracker.track("temp_file", "/tmp/test.png")
        assert tracker.count == 1

    def test_track_returns_id(self):
        tracker = ResourceTracker()
        rid = tracker.track("temp_file", "/tmp/test.png")
        assert rid == "/tmp/test.png"

    def test_track_with_metadata(self):
        tracker = ResourceTracker()
        tracker.track("screenshot", "shot_1", size=1024, format="png")
        resources = tracker.get_by_type("screenshot")
        assert len(resources) == 1
        assert resources[0].metadata["size"] == 1024

    def test_untrack_removes_resource(self):
        tracker = ResourceTracker()
        tracker.track("temp_file", "/tmp/test.png")
        assert tracker.untrack("/tmp/test.png") is True
        assert tracker.count == 0

    def test_untrack_nonexistent(self):
        tracker = ResourceTracker()
        assert tracker.untrack("nope") is False

    def test_cleanup_runs_callback(self):
        cleaned = []
        tracker = ResourceTracker()
        tracker.track("temp_file", "f1", cleanup_fn=lambda: cleaned.append("f1"))
        tracker.cleanup("f1")
        assert cleaned == ["f1"]
        assert tracker.count == 0

    def test_cleanup_nonexistent(self):
        tracker = ResourceTracker()
        assert tracker.cleanup("nope") is False

    def test_cleanup_no_callback(self):
        """Cleanup with no callback should be a no-op (not crash)."""
        tracker = ResourceTracker()
        tracker.track("temp_file", "f1")  # No cleanup_fn
        assert tracker.cleanup("f1") is True

    def test_cleanup_all(self):
        cleaned = []
        tracker = ResourceTracker()
        tracker.track("a", "1", cleanup_fn=lambda: cleaned.append("1"))
        tracker.track("b", "2", cleanup_fn=lambda: cleaned.append("2"))
        count = tracker.cleanup_all()
        assert count == 2
        assert tracker.count == 0
        assert set(cleaned) == {"1", "2"}

    def test_cleanup_older_than(self):
        tracker = ResourceTracker()
        tracker.track("old", "1")
        # Manually age the resource
        tracker._resources["1"].created_at = time.time() - 1000
        tracker.track("new", "2")
        count = tracker.cleanup_older_than(60)  # Older than 60 seconds
        assert count == 1
        assert tracker.count == 1
        assert tracker._resources.get("2") is not None

    def test_cleanup_older_than_skips_recent(self):
        tracker = ResourceTracker()
        tracker.track("fresh", "1")
        count = tracker.cleanup_older_than(60)
        assert count == 0
        assert tracker.count == 1

    def test_get_by_type(self):
        tracker = ResourceTracker()
        tracker.track("screenshot", "s1")
        tracker.track("temp_file", "t1")
        tracker.track("screenshot", "s2")
        screenshots = tracker.get_by_type("screenshot")
        assert len(screenshots) == 2
        assert tracker.get_by_type("ledger") == []

    def test_tracked_types(self):
        tracker = ResourceTracker()
        tracker.track("screenshot", "s1")
        tracker.track("temp_file", "t1")
        assert tracker.tracked_types == {"screenshot", "temp_file"}

    def test_empty_tracked_types(self):
        tracker = ResourceTracker()
        assert tracker.tracked_types == set()


class TestResourceTrackerAsync:
    @pytest.mark.asyncio
    async def test_cleanup_all_async(self):
        cleaned = []

        async def async_cleanup():
            cleaned.append("async")

        tracker = ResourceTracker()
        tracker.track("resource", "r1", cleanup_fn=async_cleanup)
        count = await tracker.cleanup_all_async()
        assert count == 1
        assert cleaned == ["async"]

    @pytest.mark.asyncio
    async def test_cleanup_all_async_mixed(self):
        cleaned = []

        tracker = ResourceTracker()
        tracker.track("a", "1", cleanup_fn=lambda: cleaned.append("sync"))
        tracker.track("b", "2", cleanup_fn=lambda: cleaned.append("sync2"))
        count = await tracker.cleanup_all_async()
        assert count == 2
        assert set(cleaned) == {"sync", "sync2"}

    @pytest.mark.asyncio
    async def test_cleanup_all_async_handles_errors(self):
        """Cleanup errors should be swallowed (best-effort)."""

        def bad_cleanup():
            raise RuntimeError("boom")

        tracker = ResourceTracker()
        tracker.track("a", "1", cleanup_fn=bad_cleanup)
        count = await tracker.cleanup_all_async()
        assert count == 1  # Still counted even though it errored


class TestTrackedResource:
    def test_age_seconds(self):
        res = TrackedResource(resource_type="test", resource_id="1")
        res.created_at = time.time() - 10
        assert res.age_seconds >= 9

    def test_metadata_default(self):
        res = TrackedResource(resource_type="test", resource_id="1")
        assert res.metadata == {}
