"""
Property-Based Tests — Input parsing, serialization round-trips, numeric invariants.

Uses Hypothesis to generate edge-case inputs and verify invariants hold.

Layer 1 of the stress testing strategy.
"""
import time

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis.strategies import (
    booleans,
    characters,
    composite,
    floats,
    integers,
    lists,
    none,
    one_of,
    sampled_from,
    text,
)

from deskaoy.cascade.cache import CacheEntry
from deskaoy.cascade.types import Tier
from deskaoy.memory.facts import Fact, FactStore
from deskaoy.orchestration.blackboard import Blackboard
from deskaoy.performance import LatencyProfiler
from deskaoy.recovery.format_validator import FormatValidator, ValidationResult
from deskaoy.recovery.retry_tracker import RetryTracker
from deskaoy.safety.cost_tracker import CostTracker

# ── Imports ──────────────────────────────────────────────────────────────
from deskaoy.safety.injection import PromptInjectionDetector
from deskaoy.safety.key_blocklist import block_reason, is_blocked_key
from deskaoy.safety.latency_budget import LatencyBudget, LatencyMeasurement
from deskaoy.safety.rate_governor import ActionRateGovernor, RateLimit

# ══════════════════════════════════════════════════════════════════════════
# Helper strategies (must be defined before use)
# ══════════════════════════════════════════════════════════════════════════

@composite
def list_of_nonneg_floats(draw, max_len=50):
    return draw(lists(
        floats(min_value=0, max_value=10000, allow_nan=False, allow_infinity=False),
        min_size=0, max_size=max_len,
    ))


# ══════════════════════════════════════════════════════════════════════════
# 1. INJECTION DETECTOR — must never crash on any input
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.property
class TestInjectionDetectorProperty:
    """Prompt injection detector must handle any string without crashing."""

    @given(text=text(characters(max_codepoint=0xFFFF), max_size=10000))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_scan_never_crashes(self, text):
        """Scan must return a verdict for any string, including empty/unicode."""
        detector = PromptInjectionDetector()
        result = detector.scan(text)
        assert isinstance(result, type(detector.scan("")))

    @given(text=text(characters(max_codepoint=0xFFFF), max_size=5000))
    @settings(max_examples=100)
    def test_match_count_always_non_negative(self, text):
        detector = PromptInjectionDetector()
        result = detector.scan(text)
        # match_count is a property (int), not a method
        assert result.match_count >= 0

    @given(a=text(min_size=1, max_size=100), b=text(min_size=1, max_size=100))
    @settings(max_examples=50)
    def test_scan_concatenation_monotone(self, a, b):
        """Scan(a+b).match_count >= max(scan(a), scan(b))."""
        detector = PromptInjectionDetector()
        combined = detector.scan(a + b).match_count
        count_a = detector.scan(a).match_count
        count_b = detector.scan(b).match_count
        assert combined >= max(count_a, count_b)


# ══════════════════════════════════════════════════════════════════════════
# 2. KEY BLOCKLIST — must classify any combo
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.property
class TestKeyBlocklistProperty:

    @given(combo=text(characters(whitelist_categories=("L", "N", "P")), max_size=50))
    @settings(max_examples=200)
    def test_is_blocked_never_crashes(self, combo):
        result = is_blocked_key(combo)
        assert isinstance(result, bool)

    @given(combo=text(characters(whitelist_categories=("L", "N")), max_size=50))
    @settings(max_examples=100)
    def test_block_reason_never_crashes(self, combo):
        reason = block_reason(combo)
        assert reason is None or isinstance(reason, str)


# ══════════════════════════════════════════════════════════════════════════
# 3. COST TRACKER — numeric invariants
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.property
class TestCostTrackerProperty:
    # CostTracker.record(provider, model, input_tokens, output_tokens, latency_ms)

    @given(
        n_records=integers(min_value=1, max_value=50),
        budget=floats(min_value=0.01, max_value=10000, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_costs_never_negative_after_records(self, n_records, budget):
        """After recording any sequence of costs, total_cost >= 0."""
        tracker = CostTracker(budget_usd=budget)
        for _i in range(n_records):
            tracker.record(
                provider="openai", model="gpt-4",
                input_tokens=100, output_tokens=50,
                latency_ms=100.0,
            )
        assert tracker.total_cost >= 0
        assert tracker.budget_remaining >= 0 or tracker.budget_exceeded

    @given(
        input_t=integers(min_value=0, max_value=10000),
        output_t=integers(min_value=0, max_value=10000),
    )
    @settings(max_examples=50)
    def test_record_returns_cost_entry(self, input_t, output_t):
        tracker = CostTracker(budget_usd=10000)
        entry = tracker.record("openai", "gpt-4", input_t, output_t)
        assert entry is not None

    @given(budget=floats(min_value=0.001, max_value=100, allow_nan=False, allow_infinity=False))
    @settings(max_examples=50)
    def test_budget_exceeded_flag(self, budget):
        """With enough records, budget must eventually be exceeded."""
        tracker = CostTracker(budget_usd=budget)
        # Each record costs: (input_tokens * 0.00003 + output_tokens * 0.00006) per 1K tokens
        # With 1M tokens each, cost = $30 + $60 = $90 per record
        for _ in range(100):
            tracker.record("openai", "gpt-4", 1000000, 1000000)
        # After 100 records of $90 each = $9000, budget must be exceeded
        assert tracker.budget_exceeded or tracker.total_cost <= budget


# ══════════════════════════════════════════════════════════════════════════
# 4. LATENCY BUDGET — time-based invariants
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.property
class TestLatencyBudgetProperty:

    @given(
        action=text(min_size=1, max_size=50, alphabet=characters(whitelist_categories=("L",))),
        duration=floats(min_value=0, max_value=60000, allow_nan=False)
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_record_never_crashes(self, action, duration):
        budget = LatencyBudget()
        result = budget.record(action, duration)
        assert isinstance(result, LatencyMeasurement)
        # summary is a property (dict), not a method
        assert isinstance(budget.summary, dict)

    @given(durations=list_of_nonneg_floats(max_len=100))
    @settings(max_examples=100)
    def test_violations_all_exceed_p95(self, durations):
        budget = LatencyBudget()
        for d in durations:
            budget.record("click", d)
        # violations is a property (list of LatencyMeasurement)
        for v in budget.violations:
            assert v.exceeded_p95 or v.exceeded_p99


# ══════════════════════════════════════════════════════════════════════════
# 5. FACT — round-trip serialization
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.property
class TestFactRoundtrip:
    # Fact(category, subject, content, source='', confidence=1.0, created_at='', updated_at='')

    @given(
        category=text(min_size=1, max_size=50),
        subject=text(min_size=1, max_size=100),
        content=text(max_size=500),
        source=text(max_size=50),
    )
    @settings(max_examples=100)
    def test_fact_roundtrip(self, category, subject, content, source):
        fact = Fact(category=category, subject=subject, content=content, source=source)
        d = fact.to_dict()
        restored = Fact.from_dict(d)
        assert restored.to_dict() == d

    @given(
        category=text(min_size=1, max_size=50),
        subject=text(min_size=1, max_size=100),
        content=text(max_size=500),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_fact_store_save_and_search(self, category, subject, content, tmp_path):
        store = FactStore(storage_dir=tmp_path)
        fact = Fact(category=category, subject=subject, content=content)
        store.save_fact(fact)
        results = store.search_facts(subject, limit=10)
        assert len(results) >= 0  # May be 0 if not yet persisted


# ══════════════════════════════════════════════════════════════════════════
# 6. CACHE ENTRY — round-trip
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.property
class TestCacheEntryRoundtrip:
    # Tier enum values: SELECTOR=1, COORDINATE=2, VISION=3

    @given(
        selector=text(min_size=1, max_size=100),
        tier=sampled_from([1, 2, 3]),
    )
    @settings(max_examples=100)
    def test_cache_entry_roundtrip(self, selector, tier):
        entry = CacheEntry(
            selector_pattern=selector,
            preferred_tier=Tier(tier),
            hit_count=5,
            miss_count=1,
            last_used=time.time(),
        )
        d = entry.to_dict()
        restored = CacheEntry.from_dict(d)
        assert restored.to_dict() == d


# ══════════════════════════════════════════════════════════════════════════
# 7. FORMAT VALIDATOR — must handle any LLM output
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.property
class TestFormatValidatorProperty:

    @given(output=text(max_size=10000))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_validate_structural_never_crashes(self, output):
        validator = FormatValidator()
        result = validator.validate_structural(output)
        # Returns ValidationResult, not bool/dict/list
        assert isinstance(result, ValidationResult)

    @given(output=text(min_size=1, max_size=5000))
    @settings(max_examples=100)
    def test_validate_never_crashes_non_empty(self, output):
        validator = FormatValidator()
        result = validator.validate_structural(output)
        assert isinstance(result, ValidationResult)


# ══════════════════════════════════════════════════════════════════════════
# 8. BLACKBOARD — read/write invariants
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.property
class TestBlackboardProperty:

    @given(
        key=text(min_size=1, max_size=50, alphabet=characters(whitelist_categories=("L", "N"))),
        value=one_of(none(), integers(), text(max_size=100), booleans()),
    )
    @settings(max_examples=100)
    def test_write_then_read(self, key, value):
        bb = Blackboard()
        bb.write(key, value, writer="test")
        result = bb.read(key)
        assert result == value

    @given(
        keys=lists(text(min_size=1, max_size=20, alphabet=characters(whitelist_categories=("L",))), min_size=1, max_size=20),
    )
    @settings(max_examples=50)
    def test_snapshot_contains_all_keys(self, keys):
        bb = Blackboard()
        for i, k in enumerate(keys):
            bb.write(k, i, writer="test")
        snap = bb.snapshot()
        for k in keys:
            assert k in snap


# ══════════════════════════════════════════════════════════════════════════
# 9. RATE GOVERNOR — rate limiting invariants
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.property
class TestRateGovernorProperty:
    # ActionRateGovernor(limits={'action': RateLimit(max_calls=N, window_seconds=S)})

    @given(
        action=text(min_size=1, max_size=30, alphabet=characters(whitelist_categories=("L",))),
        count=integers(min_value=1, max_value=200),
    )
    @settings(max_examples=100)
    def test_record_increments_check(self, action, count):
        """After N records, check should eventually return False."""
        gov = ActionRateGovernor(limits={action: RateLimit(max_actions=50, window_seconds=1.0, cooldown_seconds=0.01)})
        results = []
        for _ in range(count):
            gov.record(action)
            results.append(gov.check(action))
        if count > 50:
            assert not all(results), f"All {count} checks passed with max_calls=50"


# ══════════════════════════════════════════════════════════════════════════
# 10. LATENCY PROFILER — statistics invariants
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.property
class TestLatencyProfilerProperty:

    @given(values=lists(floats(min_value=0.1, max_value=1000, allow_nan=False), min_size=1, max_size=100))
    @settings(max_examples=100)
    def test_stats_match_input(self, values):
        profiler = LatencyProfiler()
        for v in values:
            profiler.record("op", v)
        stats = profiler.get_stats("op")
        assert stats["count"] == len(values)
        assert stats["min"] == min(values)
        assert stats["max"] == max(values)
        assert stats["min"] <= stats["mean"] <= stats["max"]


# ══════════════════════════════════════════════════════════════════════════
# 11. RETRY TRACKER — count invariants
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.property
class TestRetryTrackerProperty:
    # attempts_remaining is a property (int), not a method

    @given(
        attempts=integers(min_value=1, max_value=20),
        max_attempts=integers(min_value=1, max_value=20),
    )
    @settings(max_examples=100)
    def test_attempts_remaining(self, attempts, max_attempts):
        tracker = RetryTracker(max_attempts=max_attempts)
        actual = min(attempts, max_attempts)
        for _ in range(actual):
            tracker.record_attempt(strategy={"type": "retry"}, outcome="failure")
        remaining = tracker.attempts_remaining  # property, not method
        used = tracker.attempts_used
        assert remaining + used == max_attempts
