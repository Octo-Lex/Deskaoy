"""Tests for LatencyBudget — per-action latency budget tracking."""

from deskaoy.safety.latency_budget import LatencyBudget, LatencyMeasurement, ACTION_BUDGETS


class TestLatencyMeasurement:
    def test_construction(self):
        m = LatencyMeasurement(
            action="click", duration_ms=50.0, timestamp=1.0,
            budget_p95=200.0, budget_p99=500.0,
            exceeded_p95=False, exceeded_p99=False,
        )
        assert m.action == "click"
        assert m.duration_ms == 50.0
        assert m.exceeded is False

    def test_exceeded_property(self):
        m = LatencyMeasurement(
            action="click", duration_ms=300.0, timestamp=1.0,
            budget_p95=200.0, budget_p99=500.0,
            exceeded_p95=True, exceeded_p99=False,
        )
        assert m.exceeded is True


class TestLatencyBudget:
    def test_within_budget_check_true(self):
        lb = LatencyBudget()
        assert lb.check("click", 50.0) is True

    def test_over_p95_check_false(self):
        lb = LatencyBudget()
        assert lb.check("click", 300.0) is False

    def test_over_p99_still_checked(self):
        lb = LatencyBudget()
        # p99 is higher than p95; a value between them fails check (p95)
        assert lb.check("click", 250.0) is False

    def test_record_returns_measurement(self):
        lb = LatencyBudget()
        m = lb.record("click", 50.0)
        assert isinstance(m, LatencyMeasurement)
        assert m.action == "click"
        assert m.duration_ms == 50.0
        assert m.exceeded_p95 is False
        assert m.exceeded_p99 is False

    def test_record_flags_p95_violation(self):
        lb = LatencyBudget()
        m = lb.record("click", 300.0)
        assert m.exceeded_p95 is True
        assert m.exceeded_p99 is False

    def test_record_flags_p99_violation(self):
        lb = LatencyBudget()
        m = lb.record("click", 600.0)
        assert m.exceeded_p95 is True
        assert m.exceeded_p99 is True

    def test_summary_aggregates(self):
        lb = LatencyBudget()
        lb.record("click", 10.0)
        lb.record("click", 20.0)
        lb.record("click", 30.0)
        s = lb.summary
        assert "click" in s
        assert s["click"]["count"] == 3
        assert s["click"]["min"] == 10.0
        assert s["click"]["max"] == 30.0

    def test_violations_tracked(self):
        lb = LatencyBudget()
        lb.record("click", 50.0)
        lb.record("click", 300.0)
        v = lb.violations
        assert len(v) == 1
        assert v[0].duration_ms == 300.0

    def test_unknown_action_uses_default(self):
        lb = LatencyBudget()
        # Unknown action should use "default" budget
        assert lb.check("unknown_action", 100.0) is True
        assert lb.check("unknown_action", 600.0) is False

    def test_custom_budgets_override(self):
        custom = {"test": {"p50": 10, "p95": 20, "p99": 30}}
        lb = LatencyBudget(budgets=custom)
        assert lb.check("test", 15.0) is True
        assert lb.check("test", 25.0) is False

    def test_reset_clears_history(self):
        lb = LatencyBudget()
        lb.record("click", 50.0)
        lb.record("click", 300.0)
        assert len(lb.violations) == 1
        lb.reset()
        assert len(lb.violations) == 0
        assert lb.summary == {}

    def test_multiple_measurements_per_action(self):
        lb = LatencyBudget()
        for i in range(20):
            lb.record("click", float(i * 10))
        s = lb.summary
        assert s["click"]["count"] == 20

    def test_percentile_calculation(self):
        lb = LatencyBudget()
        for v in [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]:
            lb.record("test", v)
        s = lb.summary
        # p50 should be around 50-60
        assert s["test"]["p50"] >= 40.0

    def test_empty_budget_has_no_violations(self):
        lb = LatencyBudget()
        assert lb.violations == []
        assert lb.summary == {}

    def test_action_budgets_have_expected_entries(self):
        assert "click" in ACTION_BUDGETS
        assert "fill" in ACTION_BUDGETS
        assert "automate" in ACTION_BUDGETS
        assert "default" in ACTION_BUDGETS
