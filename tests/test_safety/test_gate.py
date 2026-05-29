"""Tests for safety gate tier-based action evaluation."""

import pytest

from deskaoy.safety.gate import (
    ActionTier,
    SafetyDecision,
    classify_tool,
    evaluate,
)


class TestActionTier:
    def test_tiers_exist(self):
        assert ActionTier.READ.value == "read"
        assert ActionTier.INPUT.value == "input"
        assert ActionTier.DESTRUCTIVE.value == "destructive"
        assert ActionTier.SYSTEM.value == "system"


class TestEvaluate:
    def test_read_action_allowed(self):
        d = evaluate("observe")
        assert d.tier == ActionTier.READ
        assert d.allowed is True
        assert d.requires_confirm is False

    def test_input_action_allowed(self):
        d = evaluate("click")
        assert d.tier == ActionTier.INPUT
        assert d.allowed is True
        assert d.requires_confirm is False

    def test_destructive_requires_confirm(self):
        d = evaluate("close_window")
        assert d.tier == ActionTier.DESTRUCTIVE
        assert d.allowed is True
        assert d.requires_confirm is True
        assert "destructive" in d.reason

    def test_system_requires_confirm(self):
        d = evaluate("execute_shell")
        assert d.tier == ActionTier.SYSTEM
        assert d.allowed is True
        assert d.requires_confirm is True
        assert "system" in d.reason

    def test_unknown_tool_is_input_tier(self):
        d = evaluate("foobar")
        assert d.tier == ActionTier.INPUT
        assert d.allowed is True

    def test_send_label_escalation(self):
        d = evaluate("click", target_label="Send Message")
        assert d.requires_confirm is True

    def test_delete_label_escalation(self):
        d = evaluate("click", target_label="Delete account")
        assert d.requires_confirm is True

    def test_safe_label_no_escalation(self):
        d = evaluate("click", target_label="Cancel")
        assert d.requires_confirm is False

    def test_sensitive_app_escalation(self):
        d = evaluate("click", app_name="Banking App Pro")
        assert d.requires_confirm is True

    def test_normal_app_no_escalation(self):
        d = evaluate("click", app_name="Notepad")
        assert d.requires_confirm is False

    def test_tier_restriction_blocks_input(self):
        d = evaluate("click", allowed_tiers={ActionTier.READ})
        assert d.allowed is False
        assert "not permitted" in d.reason

    def test_tier_restriction_allows_read(self):
        d = evaluate("observe", allowed_tiers={ActionTier.READ})
        assert d.allowed is True

    def test_tier_restriction_allows_multiple(self):
        d = evaluate("click", allowed_tiers={ActionTier.READ, ActionTier.INPUT})
        assert d.allowed is True

    def test_purchase_escalation(self):
        d = evaluate("click", target_label="Purchase Now")
        assert d.requires_confirm is True

    def test_screenshot_is_read(self):
        d = evaluate("screenshot")
        assert d.tier == ActionTier.READ


class TestClassifyTool:
    def test_known_tool(self):
        assert classify_tool("observe") == ActionTier.READ

    def test_unknown_tool(self):
        assert classify_tool("unknown") == ActionTier.INPUT

    def test_all_tiers_represented(self):
        assert classify_tool("observe") == ActionTier.READ
        assert classify_tool("click") == ActionTier.INPUT
        assert classify_tool("close_window") == ActionTier.DESTRUCTIVE
        assert classify_tool("execute_shell") == ActionTier.SYSTEM
