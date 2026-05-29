"""Tests for CostTracker — LLM cost tracking with budget enforcement."""

from deskaoy.safety.cost_tracker import CostTracker, CostEntry, PRICING


class TestCostEntry:
    def test_construction(self):
        e = CostEntry(
            provider="openai", model="gpt-4o-mini",
            input_tokens=100, output_tokens=50,
            cost_usd=0.001, latency_ms=200.0, timestamp=1.0,
        )
        assert e.provider == "openai"
        assert e.input_tokens == 100
        assert e.cost_usd == 0.001


class TestCostTracker:
    def test_record_entry_calculates_cost(self):
        ct = CostTracker(budget_usd=1.0)
        entry = ct.record("openai", "gpt-4o-mini", 1000, 500)
        assert isinstance(entry, CostEntry)
        assert entry.cost_usd > 0.0
        assert entry.input_tokens == 1000
        assert entry.output_tokens == 500

    def test_total_cost_accumulates(self):
        ct = CostTracker(budget_usd=10.0)
        ct.record("openai", "gpt-4o-mini", 1000, 500)
        ct.record("openai", "gpt-4o-mini", 1000, 500)
        assert ct.total_cost > 0.0
        # Should be ~2x a single call's cost
        single = ct.record("openai", "gpt-4o-mini", 1000, 500)
        assert ct.total_cost > single.cost_usd

    def test_budget_exceeded_detection(self):
        ct = CostTracker(budget_usd=0.0001)  # Very small budget
        assert ct.budget_exceeded is False
        # Use lots of tokens to exceed
        ct.record("openai", "gpt-4o", 100_000, 100_000)
        assert ct.budget_exceeded is True

    def test_budget_remaining(self):
        ct = CostTracker(budget_usd=1.0)
        ct.record("openai", "gpt-4o-mini", 1000, 500)
        remaining = ct.budget_remaining
        assert remaining > 0.0
        assert remaining < 1.0

    def test_summary_includes_all_fields(self):
        ct = CostTracker(budget_usd=1.0)
        ct.record("openai", "gpt-4o-mini", 1000, 500)
        s = ct.summary
        assert "total_cost_usd" in s
        assert "total_tokens" in s
        assert "budget_usd" in s
        assert "budget_remaining_usd" in s
        assert "budget_exceeded" in s
        assert "total_calls" in s
        assert "by_provider_model" in s

    def test_unknown_provider_model_uses_default(self):
        ct = CostTracker(budget_usd=10.0)
        entry = ct.record("unknown_provider", "unknown_model", 1000, 500)
        assert entry.cost_usd > 0.0  # Uses DEFAULT_PRICING

    def test_custom_budget_limit(self):
        ct = CostTracker(budget_usd=0.5)
        assert ct.budget_usd == 0.5
        assert ct.budget_remaining == 0.5

    def test_reset_clears_state(self):
        ct = CostTracker(budget_usd=1.0)
        ct.record("openai", "gpt-4o-mini", 1000, 500)
        assert ct.total_cost > 0.0
        ct.reset()
        assert ct.total_cost == 0.0
        assert ct.total_tokens == 0

    def test_zero_cost_entry(self):
        ct = CostTracker(budget_usd=1.0)
        entry = ct.record("openai", "gpt-4o-mini", 0, 0)
        assert entry.cost_usd == 0.0

    def test_multiple_providers_tracked_separately(self):
        ct = CostTracker(budget_usd=10.0)
        ct.record("openai", "gpt-4o-mini", 1000, 500)
        ct.record("anthropic", "claude-haiku-4-20250414", 1000, 500)
        s = ct.summary
        by_pm = s["by_provider_model"]
        assert "openai/gpt-4o-mini" in by_pm
        assert "anthropic/claude-haiku-4-20250414" in by_pm

    def test_budget_exactly_at_limit(self):
        ct = CostTracker(budget_usd=0.0001)
        # Keep adding tiny calls until budget is hit
        for _ in range(1000):
            ct.record("openai", "gpt-4o", 100, 100)
            if ct.budget_exceeded:
                break
        assert ct.budget_exceeded is True

    def test_cost_estimation_accuracy(self):
        """Verify cost matches manual calculation."""
        ct = CostTracker(budget_usd=10.0)
        # gpt-4o-mini: input=$0.15/1M, output=$0.60/1M
        entry = ct.record("openai", "gpt-4o-mini", 1_000_000, 1_000_000)
        expected = 0.15 + 0.60  # $0.75
        assert abs(entry.cost_usd - expected) < 0.01

    def test_total_tokens(self):
        ct = CostTracker(budget_usd=10.0)
        ct.record("openai", "gpt-4o-mini", 100, 50)
        assert ct.total_tokens == 150

    def test_pricing_table_has_known_providers(self):
        assert "openai" in PRICING
        assert "anthropic" in PRICING
        assert "gpt-4o-mini" in PRICING["openai"]
