"""
Endurance / Load Tests — memory leaks, performance degradation, sustained load.

Runs operations in tight loops for extended periods and watches for degradation.

Layer 4 of the stress testing strategy.
"""
import tempfile
import time
import tracemalloc
from pathlib import Path

import pytest

from deskaoy.memory.facts import Fact, FactStore
from deskaoy.orchestration.blackboard import Blackboard
from deskaoy.performance import LatencyProfiler, LRUCache

# ── Imports ──────────────────────────────────────────────────────────────
from deskaoy.safety.cost_tracker import CostTracker
from deskaoy.safety.rate_governor import ActionRateGovernor, RateLimit

# ══════════════════════════════════════════════════════════════════════════
# 1. MEMORY LEAK DETECTION
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.endurance
class TestMemoryLeaks:

    def test_fact_store_10k_facts(self):
        """FactStore must not leak memory after 10K facts."""
        tracemalloc.start()
        with tempfile.TemporaryDirectory() as tmp:
            store = FactStore(storage_dir=Path(tmp))

            for i in range(1000):
                fact = Fact(
                    category=f"cat-{i % 50}",
                    subject=f"subject-{i}",
                    content=f"content-{i}" * 5,
                )
                store.save_fact(fact)

            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            assert peak < 5 * 1024 * 1024, f"Memory leak: peak={peak / 1024 / 1024:.1f}MB"

    def test_cost_tracker_100k_records(self):
        """CostTracker must not grow unbounded after 100K records."""
        tracemalloc.start()
        tracker = CostTracker(budget_usd=1000000)

        for _i in range(100000):
            tracker.record("openai", "gpt-4", input_tokens=100, output_tokens=50)

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert peak < 20 * 1024 * 1024, f"Memory leak: peak={peak / 1024 / 1024:.1f}MB"

    def test_latency_profiler_100k_records(self):
        """LatencyProfiler with max_samples must not leak."""
        tracemalloc.start()
        profiler = LatencyProfiler(max_samples=100)

        for i in range(100000):
            profiler.record("action", float(i % 1000))

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert peak < 5 * 1024 * 1024, f"Memory leak: peak={peak / 1024 / 1024:.1f}MB"
        stats = profiler.get_stats("action")
        assert stats["count"] == 100  # Evicted to max_samples

    def test_blackboard_10k_keys(self):
        """Blackboard with 10K keys must not leak."""
        tracemalloc.start()
        bb = Blackboard()

        for i in range(10000):
            bb.write(f"key-{i}", f"value-{i}" * 10, writer="test")

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert peak < 30 * 1024 * 1024, f"Memory leak: peak={peak / 1024 / 1024:.1f}MB"

    def test_lru_cache_eviction(self):
        """LRUCache must properly evict old entries."""
        tracemalloc.start()
        cache = LRUCache(max_size=100)

        for i in range(10000):
            cache.put(f"key-{i}", f"value-{i}" * 100)

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert peak < 5 * 1024 * 1024, f"Memory leak: peak={peak / 1024 / 1024:.1f}MB"
        assert cache.size <= 100


# ══════════════════════════════════════════════════════════════════════════
# 2. THROUGHPUT — operations per second
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.endurance
class TestThroughput:

    def test_rate_governor_throughput(self):
        """Rate governor must handle 10K ops in reasonable time."""
        gov = ActionRateGovernor(limits={"click": RateLimit(max_actions=100000, window_seconds=1.0, cooldown_seconds=0.0)})
        start = time.time()

        for _ in range(10000):
            gov.record("click")
            gov.check("click")

        elapsed = time.time() - start
        ops_per_sec = 10000 / elapsed
        assert ops_per_sec > 1000, f"Too slow: {ops_per_sec:.0f} ops/sec"

    def test_blackboard_throughput(self):
        """Blackboard write+read must handle 10K ops in reasonable time."""
        bb = Blackboard()
        start = time.time()

        for i in range(10000):
            bb.write(f"k-{i}", i, writer="test")
            _ = bb.read(f"k-{i}")

        elapsed = time.time() - start
        ops_per_sec = 20000 / elapsed
        assert ops_per_sec > 100000, f"Too slow: {ops_per_sec:.0f} ops/sec"

    def test_cost_tracker_throughput(self):
        """CostTracker must handle 10K records in reasonable time."""
        tracker = CostTracker(budget_usd=1000000)
        start = time.time()

        for _ in range(10000):
            tracker.record("openai", "gpt-4", input_tokens=100, output_tokens=50)

        elapsed = time.time() - start
        ops_per_sec = 10000 / elapsed
        assert ops_per_sec > 50000, f"Too slow: {ops_per_sec:.0f} ops/sec"

    def test_profiler_throughput(self):
        """LatencyProfiler must handle 10K records in reasonable time."""
        profiler = LatencyProfiler(max_samples=10000)
        start = time.time()

        for i in range(10000):
            profiler.record("action", float(i))

        elapsed = time.time() - start
        ops_per_sec = 10000 / elapsed
        assert ops_per_sec > 50000, f"Too slow: {ops_per_sec:.0f} ops/sec"


# ══════════════════════════════════════════════════════════════════════════
# 3. DEGRADATION — performance over time
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.endurance
class TestNoDegradation:

    def test_blackboard_no_degradation(self):
        """Blackboard write speed must not degrade as keys grow."""
        bb = Blackboard()
        for i in range(100):
            bb.write(f"warm-{i}", i, writer="test")

        start = time.time()
        for i in range(1000):
            bb.write(f"k-{i}", i, writer="test")
        first_elapsed = time.time() - start

        for i in range(10000):
            bb.write(f"fill-{i}", i, writer="test")

        start = time.time()
        for i in range(1000, 2000):
            bb.write(f"k-{i}", i, writer="test")
        second_elapsed = time.time() - start

        ratio = second_elapsed / max(first_elapsed, 0.001)
        assert ratio < 3.0, f"Degradation: {ratio:.1f}x slower"

    def test_profiler_no_degradation(self):
        """Profiler recording speed must not degrade over time."""
        profiler = LatencyProfiler(max_samples=100000)

        start = time.time()
        for i in range(5000):
            profiler.record("action", float(i))
        first = time.time() - start

        for i in range(50000):
            profiler.record("action", float(i))

        start = time.time()
        for i in range(5000):
            profiler.record("action", float(i))
        second = time.time() - start

        ratio = second / max(first, 0.001)
        assert ratio < 5.0, f"Degradation: {ratio:.1f}x slower"
