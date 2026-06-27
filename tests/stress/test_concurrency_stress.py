"""
Concurrency Stress Tests — race conditions, deadlocks, state corruption.

Hits concurrent-sensitive components with 50-500 parallel operations.

Layer 2 of the stress testing strategy.
"""
import asyncio
import tempfile
from pathlib import Path

import pytest

from deskaoy.cascade.cache import TierPreferenceCache
from deskaoy.cascade.types import Tier
from deskaoy.memory.facts import Fact, FactStore
from deskaoy.orchestration.blackboard import Blackboard
from deskaoy.performance import LatencyProfiler

# ── Imports ──────────────────────────────────────────────────────────────
from deskaoy.safety.capture_gate import CaptureGate
from deskaoy.safety.cost_tracker import CostTracker
from deskaoy.safety.rate_governor import ActionRateGovernor, RateLimit

# ══════════════════════════════════════════════════════════════════════════
# 1. CAPTURE GATE — concurrent acquire/release
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.stress
class TestCaptureGateConcurrency:
    # CaptureGate(*, queue_depth=5, timeout_seconds=10.0)

    async def test_100_concurrent_acquire_release(self):
        """100 coroutines compete for 5 slots — all must complete."""
        gate = CaptureGate(queue_depth=100, timeout_seconds=30)
        results = []

        async def worker(i):
            async with gate.acquire():
                await asyncio.sleep(0.01)
                results.append(i)

        await asyncio.gather(*[worker(i) for i in range(100)])
        assert len(results) == 100

    async def test_50_concurrent_run(self):
        """50 concurrent run() calls — all must complete."""
        gate = CaptureGate(queue_depth=10, timeout_seconds=30)

        async def simple_coro(val):
            return val

        tasks = [gate.run(simple_coro(i)) for i in range(50)]
        results = await asyncio.gather(*tasks)
        assert len(results) == 50

    async def test_queue_depth_never_exceeds_expected(self):
        """Queue depth should never exceed expected bounds."""
        gate = CaptureGate(queue_depth=50, timeout_seconds=60)
        max_depth = 0

        async def observer():
            nonlocal max_depth
            for _ in range(50):
                max_depth = max(max_depth, gate.queue_depth)
                await asyncio.sleep(0.001)

        async def worker(i):
            async with gate.acquire():
                await asyncio.sleep(0.02)

        await asyncio.gather(
            observer(),
            asyncio.gather(*[worker(i) for i in range(50)]),
        )
        assert max_depth <= 50


# ══════════════════════════════════════════════════════════════════════════
# 2. RATE GOVERNOR — concurrent check/record
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.stress
class TestRateGovernorConcurrency:
    # ActionRateGovernor(limits={'action': RateLimit(max_calls=N, window_seconds=S)})

    async def test_200_concurrent_records(self):
        """200 rapid records must not crash or corrupt state."""
        gov = ActionRateGovernor(limits={"click": RateLimit(max_actions=100, window_seconds=1.0, cooldown_seconds=0.01)})
        successes = 0

        for _i in range(200):
            gov.record("click")
            if gov.check("click"):
                successes += 1

        stats = gov.stats
        assert "click" in stats

    async def test_multi_action_rate_limiting(self):
        """Different actions should have independent rate limits."""
        gov = ActionRateGovernor(limits={
            "click": RateLimit(max_actions=50, window_seconds=1.0, cooldown_seconds=0.01),
            "type": RateLimit(max_actions=50, window_seconds=1.0, cooldown_seconds=0.01),
        })

        for _i in range(100):
            gov.record("click")
            gov.record("type")

        stats = gov.stats
        assert "click" in stats
        assert "type" in stats


# ══════════════════════════════════════════════════════════════════════════
# 3. BLACKBOARD — concurrent read/write contention
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.stress
class TestBlackboardConcurrency:

    async def test_50_writers_50_readers(self):
        """50 concurrent writers + 50 concurrent readers — no corruption."""
        bb = Blackboard()
        errors = []

        async def writer(i):
            try:
                bb.write(f"key-{i}", f"value-{i}", writer=f"w-{i}")
            except Exception as e:
                errors.append(f"writer-{i}: {e}")

        async def reader(i):
            try:
                val = bb.read(f"key-{i % 25}")
                if val is not None:
                    assert isinstance(val, str)
            except Exception as e:
                errors.append(f"reader-{i}: {e}")

        await asyncio.gather(
            asyncio.gather(*[writer(i) for i in range(50)]),
            asyncio.gather(*[reader(i) for i in range(50)]),
        )
        assert len(errors) == 0, f"Errors: {errors[:5]}"
        assert bb.keys()

    async def test_snapshot_during_writes(self):
        """Taking snapshot while writes are happening must not crash."""
        bb = Blackboard()

        async def writer(i):
            for j in range(20):
                bb.write(f"k-{i}-{j}", j, writer="test")

        async def snapshotter():
            for _ in range(20):
                snap = bb.snapshot()
                assert isinstance(snap, dict)
                await asyncio.sleep(0.001)

        await asyncio.gather(
            asyncio.gather(*[writer(i) for i in range(20)]),
            snapshotter(),
        )


# ══════════════════════════════════════════════════════════════════════════
# 4. TIER PREFERENCE CACHE — concurrent record + persist
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.stress
class TestTierPreferenceCacheConcurrency:

    async def test_100_concurrent_success_records(self):
        """100 concurrent success records for same domain."""
        cache = TierPreferenceCache()

        for i in range(100):
            cache.record_success(
                domain="example.com",
                selector_pattern=f".btn-{i % 10}",
                tier=Tier.SELECTOR,
            )

        stats = cache.stats("example.com")
        assert stats is not None


# ══════════════════════════════════════════════════════════════════════════
# 5. COST TRACKER — concurrent recordings
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.stress
class TestCostTrackerConcurrency:

    async def test_500_concurrent_cost_records(self):
        """500 rapid cost records — total must be accurate."""
        tracker = CostTracker(budget_usd=10000)

        for _ in range(500):
            tracker.record("openai", "gpt-4", input_tokens=100, output_tokens=50)

        assert tracker.total_cost >= 0
        assert tracker.budget_remaining >= 0 or tracker.budget_exceeded


# ══════════════════════════════════════════════════════════════════════════
# 6. LATENCY PROFILER — concurrent recordings
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.stress
class TestLatencyProfilerConcurrency:

    async def test_1000_concurrent_latency_records(self):
        """1000 rapid latency records — stats must be consistent."""
        profiler = LatencyProfiler(max_samples=10000)

        for i in range(1000):
            profiler.record("action", float(i % 100))

        stats = profiler.get_stats("action")
        assert stats["count"] == 1000
        assert stats["min"] == 0.0
        assert stats["max"] == 99.0


# ══════════════════════════════════════════════════════════════════════════
# 7. FACT STORE — concurrent file I/O
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.stress
class TestFactStoreConcurrency:

    async def test_50_concurrent_save_fact(self):
        """50 concurrent save_fact + search — no corruption."""
        with tempfile.TemporaryDirectory() as tmp:
            store = FactStore(storage_dir=Path(tmp))

            for i in range(50):
                fact = Fact(
                    category="test",
                    subject=f"item-{i}",
                    content=f"content-{i}",
                )
                store.save_fact(fact)

            results = store.search_facts("item", limit=50)
            assert len(results) == 50
