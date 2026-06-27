"""Tests for performance module (BATCH-13)."""
from __future__ import annotations

import time

from deskaoy.performance import (
    LATENCY_TARGETS,
    BenchmarkSuite,
    LatencyProfiler,
    LRUCache,
    PerformanceMonitor,
    SnapshotFormatCache,
    TimingResult,
    get_global_profiler,
    timed,
)

# ── LatencyProfiler ────────────────────────────────────────────────────

class TestLatencyProfiler:
    """Test the LatencyProfiler."""

    def test_record_and_get_stats(self):
        profiler = LatencyProfiler()
        profiler.record("test_op", 10.0)
        profiler.record("test_op", 20.0)
        profiler.record("test_op", 30.0)

        stats = profiler.get_stats("test_op")
        assert stats["count"] == 3
        assert stats["min"] == 10.0
        assert stats["max"] == 30.0
        assert 19.0 <= stats["mean"] <= 21.0

    def test_empty_stats(self):
        profiler = LatencyProfiler()
        stats = profiler.get_stats("nonexistent")
        assert stats["count"] == 0

    def test_context_manager(self):
        profiler = LatencyProfiler()
        with profiler.measure("block"):
            time.sleep(0.001)  # 1ms
        stats = profiler.get_stats("block")
        assert stats["count"] == 1
        assert stats["mean"] >= 0.5  # At least 0.5ms

    def test_max_samples_eviction(self):
        profiler = LatencyProfiler(max_samples=5)
        for i in range(10):
            profiler.record("evict", float(i))
        stats = profiler.get_stats("evict")
        assert stats["count"] == 5
        assert stats["min"] == 5.0  # First 5 evicted

    def test_check_regression_pass(self):
        profiler = LatencyProfiler()
        profiler.record("click_dispatch", 10.0)
        result = profiler.check_regression("click_dispatch", target_ms=50.0)
        assert result.passed is True

    def test_check_regression_fail(self):
        profiler = LatencyProfiler()
        profiler.record("click_dispatch", 100.0)
        result = profiler.check_regression("click_dispatch", target_ms=50.0)
        assert result.passed is False

    def test_summary_output(self):
        profiler = LatencyProfiler()
        profiler.record("test", 10.0)
        summary = profiler.summary()
        assert "test" in summary

    def test_reset(self):
        profiler = LatencyProfiler()
        profiler.record("x", 1.0)
        profiler.reset()
        assert profiler.get_stats("x")["count"] == 0


# ── LRUCache ───────────────────────────────────────────────────────────

class TestLRUCache:
    """Test the generic LRU cache."""

    def test_put_and_get(self):
        cache = LRUCache(max_size=10)
        cache.put("a", 1)
        assert cache.get("a") == 1

    def test_miss_returns_none(self):
        cache = LRUCache()
        assert cache.get("missing") is None

    def test_eviction(self):
        cache = LRUCache(max_size=3)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        cache.put("d", 4)  # evicts "a"
        assert cache.get("a") is None
        assert cache.get("d") == 4

    def test_hit_rate(self):
        cache = LRUCache()
        cache.put("a", 1)
        cache.get("a")   # hit
        cache.get("a")   # hit
        cache.get("b")   # miss
        assert abs(cache.hit_rate - 0.666666) < 0.01

    def test_overwrite(self):
        cache = LRUCache()
        cache.put("a", 1)
        cache.put("a", 2)
        assert cache.get("a") == 2
        assert cache.size == 1

    def test_invalidate(self):
        cache = LRUCache()
        cache.put("a", 1)
        assert cache.invalidate("a") is True
        assert cache.get("a") is None
        assert cache.invalidate("a") is False

    def test_clear(self):
        cache = LRUCache()
        cache.put("a", 1)
        cache.get("a")
        cache.clear()
        assert cache.size == 0
        assert cache.hit_rate == 0.0

    def test_stats(self):
        cache = LRUCache(max_size=10)
        cache.put("a", 1)
        cache.get("a")
        cache.get("b")
        stats = cache.stats
        assert stats["size"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1


# ── SnapshotFormatCache ────────────────────────────────────────────────

class TestSnapshotFormatCache:
    """Test the snapshot format cache."""

    def test_cache_miss(self):
        from deskaoy.cascade.types import AXNode, AXSnapshot
        cache = SnapshotFormatCache()
        snap = AXSnapshot(url="win32://Test", title="Test", nodes={"e1": AXNode(ref="e1", role="button", name="OK")})
        assert cache.get_formatted(snap) is None

    def test_cache_hit(self):
        from deskaoy.cascade.types import AXNode, AXSnapshot
        cache = SnapshotFormatCache()
        snap = AXSnapshot(url="win32://Test", title="Test", nodes={"e1": AXNode(ref="e1", role="button", name="OK")})
        cache.put_formatted(snap, "formatted text")
        assert cache.get_formatted(snap) == "formatted text"

    def test_different_snapshots_different_keys(self):
        from deskaoy.cascade.types import AXNode, AXSnapshot
        cache = SnapshotFormatCache()
        snap1 = AXSnapshot(url="win32://A", title="A", nodes={"e1": AXNode(ref="e1", role="button", name="OK")})
        snap2 = AXSnapshot(url="win32://B", title="B", nodes={"e1": AXNode(ref="e1", role="button", name="OK")})
        cache.put_formatted(snap1, "fmt1")
        assert cache.get_formatted(snap2) is None

    def test_stats_available(self):
        cache = SnapshotFormatCache()
        assert "size" in cache.stats


# ── BenchmarkSuite ──────────────────────────────────────────────────────

class TestBenchmarkSuite:
    """Test the benchmark suite."""

    def test_run_simple(self):
        suite = BenchmarkSuite()
        suite.add("noop", lambda: None, iterations=10)
        results = suite.run()
        assert len(results) == 1
        assert results[0].name == "noop"
        assert results[0].iterations == 10
        assert results[0].passed is True  # No target, always passes

    def test_with_target(self):
        suite = BenchmarkSuite()
        suite.add("fast_op", lambda: 1 + 1, iterations=50, target_ms=1.0)
        results = suite.run()
        assert results[0].passed is True
        assert results[0].target_ms == 1.0

    def test_str_output(self):
        suite = BenchmarkSuite()
        suite.add("test", lambda: None, iterations=5, target_ms=10.0)
        results = suite.run()
        text = str(results[0])
        assert "PASS" in text or "FAIL" in text
        assert "test" in text

    def test_multiple_benchmarks(self):
        suite = BenchmarkSuite()
        suite.add("a", lambda: None, iterations=5)
        suite.add("b", lambda: time.sleep(0.001), iterations=5)
        results = suite.run()
        assert len(results) == 2
        assert results[0].name == "a"
        assert results[1].name == "b"


# ── PerformanceMonitor ─────────────────────────────────────────────────

class TestPerformanceMonitor:
    """Test the performance monitor."""

    def test_record_success(self):
        monitor = PerformanceMonitor()
        monitor.record_success("click", 15.0)
        report = monitor.health_report()
        assert report["operations"]["click"] == 1
        assert report["error_rate"] == 0.0

    def test_record_error(self):
        monitor = PerformanceMonitor()
        monitor.record_error("click")
        monitor.record_error("click")
        report = monitor.health_report()
        assert report["errors"]["click"] == 2
        assert report["error_rate"] == 1.0

    def test_mixed_operations(self):
        monitor = PerformanceMonitor()
        monitor.record_success("click", 10.0)
        monitor.record_success("click", 15.0)
        monitor.record_error("click")
        report = monitor.health_report()
        assert report["operations"]["click"] == 3
        assert abs(report["error_rate"] - 1/3) < 0.01

    def test_latency_tracking(self):
        monitor = PerformanceMonitor()
        monitor.record_success("snap", 50.0)
        monitor.record_success("snap", 100.0)
        report = monitor.health_report()
        assert "snap" in report["latency"]
        assert report["latency"]["snap"]["count"] == 2


# ── TimingResult ────────────────────────────────────────────────────────

class TestTimingResult:
    """Test timing result."""

    def test_passed_within_target(self):
        result = TimingResult(name="x", duration_ms=10.0, target_ms=50.0)
        assert result.passed is True

    def test_failed_exceeds_target(self):
        result = TimingResult(name="x", duration_ms=100.0, target_ms=50.0)
        assert result.passed is False

    def test_no_target_always_passes(self):
        result = TimingResult(name="x", duration_ms=999999.0)
        assert result.passed is True


# ── Global profiler ─────────────────────────────────────────────────────

class TestGlobalProfiler:
    """Test global profiler and timed decorator."""

    def test_global_profiler_exists(self):
        profiler = get_global_profiler()
        assert isinstance(profiler, LatencyProfiler)

    def test_timed_decorator_sync(self):
        @timed("test_fn")
        def my_fn():
            return 42
        result = my_fn()
        assert result == 42
        profiler = get_global_profiler()
        stats = profiler.get_stats("test_fn")
        assert stats["count"] >= 1


# ── Latency targets ────────────────────────────────────────────────────

class TestLatencyTargets:
    """Verify latency targets are defined for all hot paths."""

    def test_targets_exist(self):
        assert "click_dispatch" in LATENCY_TARGETS
        assert "snapshot_capture" in LATENCY_TARGETS
        assert "formatter_4pass" in LATENCY_TARGETS
        assert "agent_loop" in LATENCY_TARGETS

    def test_targets_positive(self):
        for name, target in LATENCY_TARGETS.items():
            assert target > 0, f"Target for {name} must be positive"
