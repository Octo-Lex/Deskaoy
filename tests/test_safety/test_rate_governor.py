"""Tests for ActionRateGovernor — token-bucket rate limiter."""

from deskaoy.safety.rate_governor import DEFAULT_LIMITS, ActionRateGovernor, RateLimit


class TestRateLimit:
    def test_construction(self):
        rl = RateLimit(max_actions=10, window_seconds=5.0, cooldown_seconds=1.0)
        assert rl.max_actions == 10
        assert rl.window_seconds == 5.0
        assert rl.cooldown_seconds == 1.0

    def test_default_limits_exist(self):
        assert "click" in DEFAULT_LIMITS
        assert "default" in DEFAULT_LIMITS
        assert DEFAULT_LIMITS["click"].max_actions > 0


class TestActionRateGovernor:
    def test_action_within_limit_check_true(self):
        gov = ActionRateGovernor(limits={"test": RateLimit(5, 10.0, 1.0)})
        for _ in range(4):
            gov.record("test")
        assert gov.check("test") is True

    def test_action_exceeding_limit_check_false(self):
        gov = ActionRateGovernor(limits={"test": RateLimit(3, 10.0, 1.0)})
        for _ in range(3):
            gov.record("test")
        assert gov.check("test") is False

    def test_per_action_isolation(self):
        """Click limit doesn't affect scroll."""
        gov = ActionRateGovernor(limits={
            "click": RateLimit(2, 10.0, 1.0),
            "scroll": RateLimit(100, 10.0, 0.1),
        })
        gov.record("click")
        gov.record("click")
        assert gov.check("click") is False
        assert gov.check("scroll") is True

    def test_record_increments_count(self):
        gov = ActionRateGovernor(limits={"test": RateLimit(10, 10.0, 1.0)})
        gov.record("test")
        gov.record("test")
        stats = gov.stats
        assert stats["test"]["count"] == 2

    def test_cooldown_prevents_actions(self):
        gov = ActionRateGovernor(limits={"test": RateLimit(2, 10.0, 5.0)})
        gov.record("test")
        gov.record("test")
        # Now in cooldown
        assert gov.check("test") is False

    def test_reset_single_action(self):
        gov = ActionRateGovernor(limits={"test": RateLimit(2, 10.0, 1.0)})
        gov.record("test")
        gov.record("test")
        assert gov.check("test") is False
        gov.reset("test")
        assert gov.check("test") is True

    def test_reset_all(self):
        gov = ActionRateGovernor(limits={
            "a": RateLimit(1, 10.0, 1.0),
            "b": RateLimit(1, 10.0, 1.0),
        })
        gov.record("a")
        gov.record("b")
        gov.reset()
        assert gov.check("a") is True
        assert gov.check("b") is True

    def test_default_limit_for_unknown_action(self):
        gov = ActionRateGovernor()  # uses DEFAULT_LIMITS
        # Unknown action should use "default" limit
        assert gov.check("totally_unknown_action") is True
        # Record up to default limit
        default = DEFAULT_LIMITS["default"]
        for _ in range(default.max_actions):
            gov.record("totally_unknown_action")
        assert gov.check("totally_unknown_action") is False

    def test_stats_tracking(self):
        gov = ActionRateGovernor(limits={"test": RateLimit(10, 10.0, 1.0)})
        gov.record("test")
        gov.record("test")
        stats = gov.stats
        assert "test" in stats
        assert stats["test"]["count"] == 2
        assert stats["test"]["max"] == 10
        assert stats["test"]["limited"] is False

    def test_stats_show_limited(self):
        gov = ActionRateGovernor(limits={"test": RateLimit(2, 10.0, 1.0)})
        gov.record("test")
        gov.record("test")
        stats = gov.stats
        assert stats["test"]["limited"] is True

    def test_wait_if_needed_zero_when_under_limit(self):
        gov = ActionRateGovernor(limits={"test": RateLimit(10, 10.0, 1.0)})
        gov.record("test")
        wait = gov.wait_if_needed("test")
        assert wait == 0.0

    def test_wait_if_needed_positive_when_over_limit(self):
        gov = ActionRateGovernor(limits={"test": RateLimit(2, 10.0, 5.0)})
        gov.record("test")
        gov.record("test")
        wait = gov.wait_if_needed("test")
        assert wait > 0.0

    def test_custom_limits_override(self):
        custom = {"my_action": RateLimit(1, 5.0, 0.5)}
        gov = ActionRateGovernor(limits=custom)
        gov.record("my_action")
        assert gov.check("my_action") is False
