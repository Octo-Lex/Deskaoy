"""Tests for ModelCascade."""

from deskaoy.budget.cascade import ModelCascade
from deskaoy.budget.types import (
    CascadeConfig,
    CascadeTier,
    CostTier,
)


class TestModelCascadeSelection:
    def test_click_tier_1(self):
        cascade = ModelCascade()
        result = cascade.select_model("click")
        assert result.selected_tier.tier == CostTier.TIER_1

    def test_fill_tier_1(self):
        cascade = ModelCascade()
        result = cascade.select_model("fill")
        assert result.selected_tier.tier == CostTier.TIER_1

    def test_navigate_tier_1(self):
        cascade = ModelCascade()
        result = cascade.select_model("navigate")
        assert result.selected_tier.tier == CostTier.TIER_1

    def test_compositor_click_tier_2(self):
        cascade = ModelCascade()
        result = cascade.select_model("compositor_click")
        assert result.selected_tier.tier == CostTier.TIER_2

    def test_extract_tier_2(self):
        cascade = ModelCascade()
        result = cascade.select_model("extract")
        assert result.selected_tier.tier == CostTier.TIER_2

    def test_vision_locate_tier_3_mini(self):
        cascade = ModelCascade()
        result = cascade.select_model("vision_locate")
        assert result.selected_tier.tier == CostTier.TIER_3_MINI
        assert result.selected_tier.cost_multiplier == 10.0

    def test_captcha_solve_tier_3_sonnet(self):
        cascade = ModelCascade()
        result = cascade.select_model("captcha_solve")
        assert result.selected_tier.tier == CostTier.TIER_3_SONNET
        assert result.selected_tier.cost_multiplier == 50.0

    def test_judgment_call_tier_3_opus(self):
        cascade = ModelCascade()
        result = cascade.select_model("judgment_call")
        assert result.selected_tier.tier == CostTier.TIER_3_OPUS
        assert result.selected_tier.cost_multiplier == 200.0

    def test_unknown_action_default_tier(self):
        cascade = ModelCascade()
        result = cascade.select_model("unknown_action")
        assert result.selected_tier.tier == CostTier.TIER_1

    def test_result_has_model_and_provider(self):
        cascade = ModelCascade()
        result = cascade.select_model("click")
        assert result.model != ""
        assert result.provider != ""


class TestModelCascadeEscalation:
    def test_escalate_tier_1_to_2(self):
        cascade = ModelCascade()
        result = cascade.escalate(CostTier.TIER_1, "action_failed")
        assert result is not None
        assert result.escalated_from == CostTier.TIER_1
        assert result.selected_tier.tier == CostTier.TIER_2

    def test_escalate_tier_2_to_3_mini(self):
        cascade = ModelCascade()
        result = cascade.escalate(CostTier.TIER_2, "action_failed")
        assert result is not None
        assert result.selected_tier.tier == CostTier.TIER_3_MINI

    def test_escalation_count_increments(self):
        cascade = ModelCascade()
        cascade.escalate(CostTier.TIER_1, "fail")
        result = cascade.escalate(CostTier.TIER_2, "fail")
        assert result is not None
        assert result.escalation_count >= 2

    def test_max_escalations_returns_none(self):
        cascade = ModelCascade(CascadeConfig(max_total_escalations=3))
        cascade.escalate(CostTier.TIER_1, "fail")
        cascade.escalate(CostTier.TIER_2, "fail")
        cascade.escalate(CostTier.TIER_3_MINI, "fail")
        result = cascade.escalate(CostTier.TIER_3_SONNET, "fail")
        assert result is None

    def test_escalate_from_last_tier_returns_none(self):
        cascade = ModelCascade()
        result = cascade.escalate(CostTier.TIER_3_OPUS, "fail")
        assert result is None

    def test_reset_escalations(self):
        cascade = ModelCascade(CascadeConfig(max_total_escalations=1))
        cascade.escalate(CostTier.TIER_1, "fail")
        assert cascade.escalate(CostTier.TIER_2, "fail") is None
        cascade.reset_escalations()
        result = cascade.escalate(CostTier.TIER_2, "fail")
        assert result is not None


class TestModelCascadeGetTier:
    def test_get_existing_tier(self):
        cascade = ModelCascade()
        tier = cascade.get_tier(CostTier.TIER_1)
        assert tier is not None
        assert tier.model == "claude-haiku-4-20250414"

    def test_get_all_default_tiers(self):
        cascade = ModelCascade()
        for ct in CostTier:
            assert cascade.get_tier(ct) is not None

    def test_custom_config(self):
        custom_tiers = (
            CascadeTier(tier=CostTier.TIER_1, model="custom-model", provider="test", cost_multiplier=1.0),
        )
        cascade = ModelCascade(CascadeConfig(tiers=custom_tiers))
        tier = cascade.get_tier(CostTier.TIER_1)
        assert tier is not None
        assert tier.model == "custom-model"


class TestH2GovernorBudgetCheck:
    """H2: Escalation must be blocked when governor says budget is exhausted."""

    def test_escalation_blocked_when_budget_exhausted(self):
        from deskaoy.budget.governor import TokenBudgetGovernor
        from deskaoy.budget.types import BudgetConfig

        # Exhaust the daily budget
        config = BudgetConfig(daily_cap_usd=0.001)
        governor = TokenBudgetGovernor(config)
        governor._state.daily_spend_usd = 1.0  # well over cap

        cascade = ModelCascade(governor=governor)
        result = cascade.escalate(CostTier.TIER_1, "need better model")
        assert result is None  # blocked by budget

    def test_escalation_allowed_when_budget_available(self):
        from deskaoy.budget.governor import TokenBudgetGovernor

        governor = TokenBudgetGovernor()  # fresh, has budget
        cascade = ModelCascade(governor=governor)
        result = cascade.escalate(CostTier.TIER_1, "need better model")
        assert result is not None  # allowed

    def test_escalation_without_governor_works(self):
        """Backward compat: no governor means escalation works as before."""
        cascade = ModelCascade(governor=None)
        result = cascade.escalate(CostTier.TIER_1, "need better model")
        assert result is not None

    def test_escalation_blocked_then_allowed_after_reset(self):
        """After daily reset, escalation should be allowed again."""
        from deskaoy.budget.governor import TokenBudgetGovernor
        from deskaoy.budget.types import BudgetConfig

        config = BudgetConfig(daily_cap_usd=0.001)
        governor = TokenBudgetGovernor(config)
        governor._state.daily_spend_usd = 1.0

        cascade = ModelCascade(governor=governor)
        assert cascade.escalate(CostTier.TIER_1, "fail") is None

        # Reset budget and escalation counts — use a generous cap
        governor.reset_daily()
        governor._config = BudgetConfig(daily_cap_usd=100.0)  # generous cap
        cascade.reset_escalations()
        result = cascade.escalate(CostTier.TIER_1, "fail")
        assert result is not None
