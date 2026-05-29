"""Performance profiling, caching, and latency benchmarks.

Provides:
  - LatencyProfiler: measure and report hot-path timings
  - LRUCache: generic LRU cache for expensive lookups
  - BenchmarkSuite: latency regression tests
  - PerformanceMonitor: real-time performance tracking

Targets:
  - click dispatch < 50ms
  - snapshot capture < 200ms
  - formatter < 30ms
  - full agent loop < 2000ms
"""

from __future__ import annotations

import logging
import statistics
import time
from collections import OrderedDict
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Generic, Optional, TypeVar

logger = logging.getLogger(__name__)

K = TypeVar("K")
V = TypeVar("V")

# ── Latency targets (ms) ───────────────────────────────────────────────

LATENCY_TARGETS: dict[str, float] = {
    "click_dispatch": 50.0,
    "snapshot_capture": 200.0,
    "formatter_4pass": 30.0,
    "memory_recall": 20.0,
    "memory_record": 30.0,
    "cascade_tier1": 10.0,
    "cascade_tier2": 50.0,
    "agent_loop": 2000.0,
    "key_press": 50.0,
    "type_text": 100.0,
}


# ── Timing result ───────────────────────────────────────────────────────

@dataclass
class TimingResult:
    """Single timing measurement."""
    name: str
    duration_ms: float
    target_ms: float | None = None
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def passed(self) -> bool:
        """True if within latency target."""
        if self.target_ms is None:
            return True
        return self.duration_ms <= self.target_ms


# ── Latency Profiler ────────────────────────────────────────────────────

class LatencyProfiler:
    """Collect and report latency measurements for hot paths.

    Usage:
        profiler = LatencyProfiler()
        with profiler.measure("click_dispatch"):
            await adapter.click("btn")
        print(profiler.summary())
    """

    def __init__(self, max_samples: int = 1000) -> None:
        self._samples: dict[str, list[float]] = {}
        self._max_samples = max_samples

    @contextmanager
    def measure(self, name: str):
        """Context manager to measure a code block's duration."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - start) * 1000.0
            self.record(name, elapsed)

    def record(self, name: str, duration_ms: float) -> None:
        """Record a timing sample."""
        samples = self._samples.setdefault(name, [])
        samples.append(duration_ms)
        if len(samples) > self._max_samples:
            samples.pop(0)

    def get_stats(self, name: str) -> dict[str, float]:
        """Get statistics for a named measurement."""
        samples = self._samples.get(name, [])
        if not samples:
            return {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
        sorted_s = sorted(samples)
        return {
            "count": len(samples),
            "mean": statistics.mean(samples),
            "p50": sorted_s[len(sorted_s) // 2],
            "p95": sorted_s[int(len(sorted_s) * 0.95)],
            "p99": sorted_s[min(len(sorted_s) - 1, int(len(sorted_s) * 0.99))],
            "max": sorted_s[-1],
            "min": sorted_s[0],
        }

    def check_regression(self, name: str, target_ms: float | None = None) -> TimingResult:
        """Check if the latest sample exceeds the latency target."""
        samples = self._samples.get(name, [])
        if not samples:
            return TimingResult(name=name, duration_ms=0.0, target_ms=target_ms)

        target = target_ms or LATENCY_TARGETS.get(name)
        latest = samples[-1]
        return TimingResult(name=name, duration_ms=latest, target_ms=target)

    def summary(self) -> str:
        """Generate a human-readable summary of all measurements."""
        lines = ["Latency Profile:"]
        for name in sorted(self._samples.keys()):
            stats = self.get_stats(name)
            target = LATENCY_TARGETS.get(name)
            target_str = f"/{target:.0f}ms" if target else ""
            status = "✓" if not target or stats["p95"] <= target else "✗"
            lines.append(
                f"  {status} {name}: "
                f"p50={stats['p50']:.1f}ms p95={stats['p95']:.1f}ms{target_str} "
                f"(n={stats['count']})"
            )
        return "\n".join(lines)

    def reset(self) -> None:
        """Clear all recorded samples."""
        self._samples.clear()


# ── LRU Cache ───────────────────────────────────────────────────────────

class LRUCache(Generic[K, V]):
    """Generic LRU cache with size limit and hit/miss stats.

    Used for expensive lookups like memory fingerprint hashing,
    selector resolution, and snapshot formatting.
    """

    def __init__(self, max_size: int = 256) -> None:
        self._max_size = max_size
        self._cache: OrderedDict[K, V] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, key: K) -> V | None:
        """Get a value from cache, returning None if not found."""
        if key in self._cache:
            self._hits += 1
            self._cache.move_to_end(key)
            return self._cache[key]
        self._misses += 1
        return None

    def put(self, key: K, value: V) -> None:
        """Put a value into cache, evicting LRU if needed."""
        if key in self._cache:
            self._cache.move_to_end(key)
            self._cache[key] = value
        else:
            self._cache[key] = value
            if len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def invalidate(self, key: K) -> bool:
        """Remove a key from cache. Returns True if it existed."""
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> None:
        """Clear all entries and reset stats."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self.hit_rate,
            "evictions": max(0, self._hits + self._misses - self._max_size),
        }


# ── Snapshot format cache ──────────────────────────────────────────────

class SnapshotFormatCache:
    """Cache for formatted AX snapshots.

    Keyed by snapshot hash (url + title + node count + first node ref).
    Avoids re-formatting unchanged snapshots.
    """

    def __init__(self, max_size: int = 32) -> None:
        self._cache = LRUCache[str, str](max_size=max_size)

    def _snapshot_key(self, snapshot: Any) -> str:
        """Generate a cache key from snapshot metadata."""
        node_count = len(snapshot.nodes) if hasattr(snapshot, "nodes") else 0
        url = getattr(snapshot, "url", "") or ""
        title = getattr(snapshot, "title", "") or ""
        return f"{url}:{title}:{node_count}"

    def get_formatted(self, snapshot: Any) -> str | None:
        """Get cached formatted text for a snapshot."""
        return self._cache.get(self._snapshot_key(snapshot))

    def put_formatted(self, snapshot: Any, formatted: str) -> None:
        """Cache a formatted snapshot."""
        self._cache.put(self._snapshot_key(snapshot), formatted)

    @property
    def stats(self) -> dict[str, Any]:
        return self._cache.stats


# ── Timed decorator ─────────────────────────────────────────────────────

_global_profiler = LatencyProfiler()


def timed(name: str) -> Callable:
    """Decorator to time a function and record in the global profiler.

    Usage:
        @timed("formatter_4pass")
        def format_snapshot(snapshot):
            ...
    """
    def decorator(fn: Callable) -> Callable:
        if asyncio.iscoroutinefunction(fn):
            @wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                start = time.perf_counter()
                try:
                    return await fn(*args, **kwargs)
                finally:
                    elapsed = (time.perf_counter() - start) * 1000.0
                    _global_profiler.record(name, elapsed)
            return async_wrapper
        else:
            @wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                start = time.perf_counter()
                try:
                    return fn(*args, **kwargs)
                finally:
                    elapsed = (time.perf_counter() - start) * 1000.0
                    _global_profiler.record(name, elapsed)
            return sync_wrapper
    return decorator


def get_global_profiler() -> LatencyProfiler:
    """Get the global profiler instance."""
    return _global_profiler


# ── Benchmark Suite ─────────────────────────────────────────────────────

@dataclass
class BenchmarkResult:
    """Result of running a benchmark."""
    name: str
    iterations: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float
    target_ms: float | None
    passed: bool

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        target_str = f" (target: {self.target_ms:.0f}ms)" if self.target_ms else ""
        return f"[{status}] {self.name}: {self.mean_ms:.2f}ms p95={self.p95_ms:.2f}ms{target_str}"


class BenchmarkSuite:
    """Suite of micro-benchmarks for regression testing.

    Usage:
        suite = BenchmarkSuite()
        suite.add("memory_lookup", lambda: memory.recall("click", "win", "notepad"), target_ms=20)
        results = suite.run()
        for r in results:
            print(r)
    """

    def __init__(self) -> None:
        self._benchmarks: list[tuple[str, Callable, int, float | None]] = []

    def add(
        self,
        name: str,
        fn: Callable,
        iterations: int = 100,
        target_ms: float | None = None,
    ) -> BenchmarkSuite:
        """Add a benchmark to the suite."""
        self._benchmarks.append((name, fn, iterations, target_ms))
        return self

    def run(self) -> list[BenchmarkResult]:
        """Run all benchmarks and return results."""
        results = []
        for name, fn, iterations, target_ms in self._benchmarks:
            samples = []
            for _ in range(iterations):
                start = time.perf_counter()
                fn()
                elapsed = (time.perf_counter() - start) * 1000.0
                samples.append(elapsed)

            sorted_s = sorted(samples)
            result = BenchmarkResult(
                name=name,
                iterations=iterations,
                mean_ms=statistics.mean(samples),
                p50_ms=sorted_s[len(sorted_s) // 2],
                p95_ms=sorted_s[int(len(sorted_s) * 0.95)],
                max_ms=sorted_s[-1],
                target_ms=target_ms,
                passed=target_ms is None or sorted_s[int(len(sorted_s) * 0.95)] <= target_ms,
            )
            results.append(result)
        return results


# ── Performance Monitor ─────────────────────────────────────────────────

class PerformanceMonitor:
    """Real-time performance monitor for agent operations.

    Tracks operation counts, error rates, and latency percentiles.
    Can be queried for health reporting.
    """

    def __init__(self, window_size: int = 100) -> None:
        self._profiler = LatencyProfiler(max_samples=window_size)
        self._counts: dict[str, int] = {}
        self._errors: dict[str, int] = {}

    def record_success(self, operation: str, duration_ms: float) -> None:
        """Record a successful operation."""
        self._profiler.record(operation, duration_ms)
        self._counts[operation] = self._counts.get(operation, 0) + 1

    def record_error(self, operation: str) -> None:
        """Record a failed operation."""
        self._errors[operation] = self._errors.get(operation, 0) + 1
        self._counts[operation] = self._counts.get(operation, 0) + 1

    @property
    def error_rate(self) -> float:
        """Overall error rate (0.0 to 1.0)."""
        total_ops = sum(self._counts.values())
        total_errors = sum(self._errors.values())
        return total_errors / total_ops if total_ops > 0 else 0.0

    def health_report(self) -> dict[str, Any]:
        """Generate a performance health report."""
        return {
            "operations": dict(self._counts),
            "errors": dict(self._errors),
            "error_rate": self.error_rate,
            "latency": {
                name: self._profiler.get_stats(name)
                for name in self._profiler._samples
            },
        }


# Handle import for async check
import asyncio
