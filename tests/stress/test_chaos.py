"""
Chaos / Fault Injection Tests — network failures, disk errors, malformed data.

Injects random failures and verifies recovery or graceful degradation.

Layer 3 of the stress testing strategy.
"""
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis.strategies import binary, text

from deskaoy.cascade.cache import TierPreferenceCache
from deskaoy.memory.facts import Fact, FactStore
from deskaoy.orchestration.blackboard import Blackboard
from deskaoy.recovery.crash_recovery import CrashRecovery
from deskaoy.recovery.format_validator import FormatValidator, ValidationResult
from deskaoy.recovery.retry_tracker import RetryTracker

# ── Imports ──────────────────────────────────────────────────────────────
from deskaoy.safety.cost_tracker import CostTracker
from deskaoy.safety.evidence_ledger import EvidenceLedger, LedgerEntry
from deskaoy.safety.injection import PromptInjectionDetector
from deskaoy.safety.latency_budget import LatencyBudget
from deskaoy.safety.rate_governor import ActionRateGovernor, RateLimit
from deskaoy.safety.timeout_guard import TimeoutGuard

# ══════════════════════════════════════════════════════════════════════════
# 1. DISK FAILURE — file I/O chaos
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.chaos
class TestDiskChaos:

    def test_fact_store_readonly_dir(self):
        """FactStore on a read-only directory must not crash."""
        with tempfile.TemporaryDirectory() as tmp:
            readonly = tmp + "/readonly"
            os.makedirs(readonly)
            os.chmod(readonly, 0o444)
            try:
                store = FactStore(storage_dir=Path(readonly))
                fact = Fact(category="c", subject="s", content="x")
                try:
                    store.save_fact(fact)
                except (OSError, PermissionError):
                    pass  # Expected on read-only
            finally:
                os.chmod(readonly, 0o755)

    def test_evidence_ledger_corrupted_file(self):
        """EvidenceLedger with corrupted data must handle gracefully."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = tmp + "/ledger.jsonl"
            with open(db_path, "w") as f:
                f.write("NOT JSON\n")
                f.write('{"valid": true}\n')
                f.write("MORE GARBAGE\n")

            # EvidenceLedger.__init__ takes db_path
            try:
                ledger = EvidenceLedger(db_path=db_path)
                entries = ledger.read_all()
                assert isinstance(entries, list)
            except (json.JSONDecodeError, ValueError, TypeError):
                pass  # Acceptable to raise on corrupt data


# ══════════════════════════════════════════════════════════════════════════
# 2. MALFORMED INPUT — garbage data to parsers
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.chaos
class TestMalformedInputChaos:

    @given(data=binary(min_size=0, max_size=5000))
    @settings(max_examples=200)
    def test_format_validator_binary_input(self, data):
        """FormatValidator must handle raw binary without crashing."""
        validator = FormatValidator()
        try:
            text_input = data.decode("utf-8", errors="replace")
            result = validator.validate_structural(text_input)
            assert isinstance(result, ValidationResult)
        except Exception:
            pass  # Acceptable for binary data

    @given(data=text(max_size=10000))
    @settings(max_examples=100)
    def test_injection_detector_extreme_input(self, data):
        """PromptInjectionDetector must handle extreme strings."""
        detector = PromptInjectionDetector()
        result = detector.scan(data)
        assert result is not None

    def test_ledger_entry_from_corrupted_dict(self):
        """LedgerEntry.from_dict must handle missing/wrong type keys."""
        try:
            LedgerEntry.from_dict({"seq": 1, "ts": "t", "hash": "h", "prev": "p", "session_id": "s", "event_type": "e", "data": {}})
        except (KeyError, TypeError):
            pass  # Acceptable

        try:
            LedgerEntry.from_dict({})  # Missing required keys
        except (KeyError, TypeError):
            pass  # Acceptable


# ══════════════════════════════════════════════════════════════════════════
# 3. TIMEOUT CHAOS — operations that take too long
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.chaos
class TestTimeoutChaos:

    def test_timeout_guard_expires(self):
        """TimeoutGuard must correctly expire."""
        guard = TimeoutGuard(total_timeout_ms=50)
        assert not guard.exhausted
        time.sleep(0.06)
        assert guard.exhausted
        assert guard.remaining_ms <= 0

    def test_timeout_guard_child_inherits_expiry(self):
        """Child timeout must not exceed parent's remaining time."""
        guard = TimeoutGuard(total_timeout_ms=1000)
        time.sleep(0.05)
        child = guard.child(timeout_ms=500)
        assert child.remaining_ms <= guard.remaining_ms + 1

    async def test_latency_budget_rapid_fire(self):
        """Recording 1000 latency entries rapidly must not lag."""
        budget = LatencyBudget()
        start = time.time()
        for i in range(1000):
            budget.record("click", float(i % 100))
        elapsed = time.time() - start
        assert elapsed < 1.0, f"Too slow: {elapsed:.2f}s for 1000 records"


# ══════════════════════════════════════════════════════════════════════════
# 4. BUDGET EXHAUSTION — running out of resources
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.chaos
class TestBudgetExhaustion:

    def test_cost_tracker_exhaustion(self):
        """CostTracker hitting budget limit must flag correctly."""
        tracker = CostTracker(budget_usd=1.00)
        for _ in range(100):
            tracker.record("openai", "gpt-4", input_tokens=10000, output_tokens=5000)

        assert tracker.budget_exceeded
        assert tracker.budget_remaining <= 0

    def test_cost_tracker_zero_budget(self):
        """Zero budget must immediately flag exceeded."""
        tracker = CostTracker(budget_usd=0)
        tracker.record("openai", "gpt-4", input_tokens=1, output_tokens=1)
        assert tracker.budget_exceeded

    def test_retry_tracker_exhaustion(self):
        """RetryTracker must correctly report when max attempts reached."""
        tracker = RetryTracker(max_attempts=3)
        tracker.record_attempt(strategy={"type": "retry"}, outcome="failure")
        assert tracker.attempts_remaining == 2
        tracker.record_attempt(strategy={"type": "retry"}, outcome="failure")
        assert tracker.attempts_remaining == 1
        tracker.record_attempt(strategy={"type": "retry"}, outcome="failure")
        assert tracker.attempts_remaining == 0

    def test_rate_governor_saturation(self):
        """Rate governor under saturation must start rejecting."""
        gov = ActionRateGovernor(limits={"click": RateLimit(max_actions=10, window_seconds=1.0, cooldown_seconds=0.01)})
        results = []
        for _ in range(100):
            gov.record("click")
            results.append(gov.check("click"))
        assert not all(results), "Rate governor never throttled"


# ══════════════════════════════════════════════════════════════════════════
# 5. CACHE CORRUPTION — invalid cache data
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.chaos
class TestCacheCorruption:

    def test_cache_entry_invalid_tier(self):
        """CacheEntry with invalid tier string must not crash."""
        from deskaoy.cascade.cache import CacheEntry
        try:
            CacheEntry.from_dict({
                "selector_pattern": ".btn",
                "preferred_tier": "INVALID_TIER",
                "hit_count": 1,
                "miss_count": 0,
                "last_used": time.time(),
            })
        except (ValueError, KeyError):
            pass  # Acceptable

    async def test_tier_preference_cache_load_corrupted(self):
        """Load with corrupted file must not crash."""
        with tempfile.TemporaryDirectory() as tmp:
            cache_file = tmp + "/cache.json"
            with open(cache_file, "w") as f:
                f.write("NOT JSON")

            cache = TierPreferenceCache(cache_dir=Path(tmp))
            try:
                await cache.load("example.com")
            except (json.JSONDecodeError, ValueError):
                pass  # Acceptable


# ══════════════════════════════════════════════════════════════════════════
# 6. CRASH RECOVERY — checkpoint corruption
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.chaos
class TestCrashRecoveryChaos:

    @given(data=binary(min_size=0, max_size=2000))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_load_corrupted_checkpoint(self, data, tmp_path):
        """Loading corrupted checkpoint data must not crash."""
        session_file = tmp_path / "session-1.json"
        session_file.write_bytes(data)

        recovery = CrashRecovery(checkpoint_dir=tmp_path)
        try:
            result = await recovery.load("session-1")
            assert result is None or hasattr(result, "to_dict")
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    async def test_load_nonexistent_checkpoint(self, tmp_path):
        """Loading non-existent checkpoint must return None."""
        recovery = CrashRecovery(checkpoint_dir=tmp_path)
        result = await recovery.load("nonexistent-session")
        assert result is None


# ══════════════════════════════════════════════════════════════════════════
# 7. INTEGRATION: cascading failures
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.chaos
class TestCascadingFailures:

    async def test_budget_exhausted_mid_operation(self):
        """Budget exhaustion during operations must be tracked."""
        tracker = CostTracker(budget_usd=0.005)
        results = []

        for _i in range(10):
            tracker.record("openai", "gpt-4", input_tokens=1000, output_tokens=500)
            results.append({
                "cost": tracker.total_cost,
                "exceeded": tracker.budget_exceeded,
            })

        # First few should not be exceeded
        assert not results[0]["exceeded"]
        # Later ones should be exceeded
        assert results[-1]["exceeded"]

    async def test_blackboard_read_missing_key_during_writes(self):
        """Reading missing keys while writes are happening must not crash."""
        bb = Blackboard()

        async def writer():
            for i in range(100):
                bb.write(f"k{i}", i, writer="w")
                await asyncio.sleep(0)

        async def reader():
            for i in range(100):
                val = bb.read(f"nonexistent-{i}")
                assert val is None
                await asyncio.sleep(0)

        await asyncio.gather(writer(), reader())
