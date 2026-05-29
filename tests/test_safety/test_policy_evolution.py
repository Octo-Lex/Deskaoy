"""Tests for Policy Self-Evolution — learn from denials instead of just blocking."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from deskaoy.safety.policy_evolution import (
    DenialCategory,
    EvolutionDecision,
    PolicyEvolutionEngine,
    PolicySuggestion,
    EvolutionResult,
    suggest_policy_change,
)


# ---------------------------------------------------------------------------
# suggest_policy_change
# ---------------------------------------------------------------------------

class TestSuggestPolicyChange:
    # --- Suggestible ---

    def test_no_capability_for_tool(self) -> None:
        s = suggest_policy_change("click", "No capability defined for tool 'click'")
        assert s is not None
        assert s.category == DenialCategory.NO_CAPABILITY
        assert s.tool == "click"
        assert "click" in s.description
        assert s.change["type"] == "add_capability"

    def test_no_capability_for_action_variant(self) -> None:
        s = suggest_policy_change("scroll", "No capability for action 'scroll'")
        assert s is not None
        assert s.category == DenialCategory.NO_CAPABILITY
        assert s.tool == "scroll"

    def test_path_scope_violation(self) -> None:
        s = suggest_policy_change("navigate", 'Path "/etc/passwd" is outside allowed scope')
        assert s is not None
        assert s.category == DenialCategory.SCOPE_VIOLATION
        assert s.change["type"] == "widen_scope"
        assert s.change["field"] == "paths"
        assert "/etc/passwd" in s.change["add"]

    def test_domain_scope_violation(self) -> None:
        s = suggest_policy_change("navigate", 'Domain "evil.com" is not in allowed list')
        assert s is not None
        assert s.category == DenialCategory.SCOPE_VIOLATION
        assert s.change["field"] == "domains"
        assert "evil.com" in s.change["add"]

    def test_blocked_by_policy(self) -> None:
        s = suggest_policy_change("click", "Action blocked by policy")
        assert s is not None
        assert s.category == DenialCategory.SCOPE_VIOLATION
        assert s.change["type"] == "widen_scope"

    def test_blocked_by_policy_case_insensitive(self) -> None:
        s = suggest_policy_change("click", "Action BLOCKED BY POLICY for this user")
        assert s is not None
        assert s.category == DenialCategory.SCOPE_VIOLATION

    def test_forbidden_pattern(self) -> None:
        s = suggest_policy_change("execute", 'Command matches forbidden pattern "rm -rf"')
        assert s is not None
        assert s.category == DenialCategory.FORBIDDEN_MATCH
        assert s.change["type"] == "remove_forbidden"
        assert s.change["pattern"] == "rm -rf"

    # --- NOT suggestible ---

    def test_budget_exceeded_not_suggestible(self) -> None:
        s = suggest_policy_change("click", "Budget exceeded for this session")
        assert s is None

    def test_cost_limit_not_suggestible(self) -> None:
        s = suggest_policy_change("click", "Cost limit reached ($1.00)")
        assert s is None

    def test_rate_limit_not_suggestible(self) -> None:
        s = suggest_policy_change("click", "Rate limit exceeded")
        assert s is None

    def test_session_action_limit_not_suggestible(self) -> None:
        s = suggest_policy_change("click", "Session action limit reached")
        assert s is None

    def test_session_denial_limit_not_suggestible(self) -> None:
        s = suggest_policy_change("click", "Session denial limit reached")
        assert s is None

    def test_empty_reason_not_suggestible(self) -> None:
        s = suggest_policy_change("click", "")
        assert s is None

    def test_unknown_reason_not_suggestible(self) -> None:
        s = suggest_policy_change("click", "Something went wrong internally")
        assert s is None

    # --- Description quality ---

    def test_no_capability_description_readable(self) -> None:
        s = suggest_policy_change("type", "No capability defined for tool 'type'")
        assert s is not None
        assert "type" in s.description
        assert "?" in s.description

    def test_scope_description_mentions_value(self) -> None:
        s = suggest_policy_change("click", 'Domain "example.com" is not in allowed list')
        assert s is not None
        assert "example.com" in s.description


# ---------------------------------------------------------------------------
# PolicyEvolutionEngine
# ---------------------------------------------------------------------------

class TestPolicyEvolutionEngine:
    def test_suggest_delegates(self) -> None:
        engine = PolicyEvolutionEngine()
        s = engine.suggest("click", "No capability defined for tool 'click'")
        assert s is not None
        assert s.tool == "click"

    def test_suggest_returns_none_for_hard_limit(self) -> None:
        engine = PolicyEvolutionEngine()
        s = engine.suggest("click", "Budget exceeded for this session")
        assert s is None

    @pytest.mark.asyncio
    async def test_evolve_no_handler_returns_deny(self) -> None:
        engine = PolicyEvolutionEngine(handler=None)
        suggestion = PolicySuggestion(
            category=DenialCategory.NO_CAPABILITY,
            tool="click",
            description='Add "click"?',
            change={"type": "add_capability", "tool": "click", "scope": {}},
        )
        result = await engine.evolve(suggestion)
        assert result.decision == EvolutionDecision.DENY
        assert result.suggestion is suggestion

    @pytest.mark.asyncio
    async def test_evolve_handler_add_to_policy(self) -> None:
        async def handler(s: PolicySuggestion) -> EvolutionDecision:
            return EvolutionDecision.ADD_TO_POLICY

        engine = PolicyEvolutionEngine(handler=handler)
        suggestion = PolicySuggestion(
            category=DenialCategory.NO_CAPABILITY,
            tool="click",
            description='Add "click"?',
            change={"type": "add_capability", "tool": "click", "scope": {}},
        )
        result = await engine.evolve(suggestion)
        assert result.decision == EvolutionDecision.ADD_TO_POLICY

    @pytest.mark.asyncio
    async def test_evolve_handler_allow_once(self) -> None:
        async def handler(s: PolicySuggestion) -> EvolutionDecision:
            return EvolutionDecision.ALLOW_ONCE

        engine = PolicyEvolutionEngine(handler=handler)
        suggestion = PolicySuggestion(
            category=DenialCategory.NO_CAPABILITY,
            tool="click",
            description='Add "click"?',
            change={"type": "add_capability", "tool": "click", "scope": {}},
        )
        result = await engine.evolve(suggestion)
        assert result.decision == EvolutionDecision.ALLOW_ONCE

    @pytest.mark.asyncio
    async def test_evolve_handler_deny(self) -> None:
        async def handler(s: PolicySuggestion) -> EvolutionDecision:
            return EvolutionDecision.DENY

        engine = PolicyEvolutionEngine(handler=handler)
        suggestion = PolicySuggestion(
            category=DenialCategory.NO_CAPABILITY,
            tool="click",
            description='Add "click"?',
            change={"type": "add_capability", "tool": "click", "scope": {}},
        )
        result = await engine.evolve(suggestion)
        assert result.decision == EvolutionDecision.DENY

    @pytest.mark.asyncio
    async def test_evolve_timeout_returns_deny(self) -> None:
        async def slow_handler(s: PolicySuggestion) -> EvolutionDecision:
            await asyncio.sleep(10)  # Way past timeout
            return EvolutionDecision.ADD_TO_POLICY

        engine = PolicyEvolutionEngine(handler=slow_handler, timeout_ms=100)
        suggestion = PolicySuggestion(
            category=DenialCategory.NO_CAPABILITY,
            tool="click",
            description='Add "click"?',
            change={"type": "add_capability", "tool": "click", "scope": {}},
        )
        result = await engine.evolve(suggestion)
        assert result.decision == EvolutionDecision.DENY

    @pytest.mark.asyncio
    async def test_evolve_handler_exception_returns_deny(self) -> None:
        async def bad_handler(s: PolicySuggestion) -> EvolutionDecision:
            raise RuntimeError("boom")

        engine = PolicyEvolutionEngine(handler=bad_handler)
        suggestion = PolicySuggestion(
            category=DenialCategory.NO_CAPABILITY,
            tool="click",
            description='Add "click"?',
            change={"type": "add_capability", "tool": "click", "scope": {}},
        )
        result = await engine.evolve(suggestion)
        assert result.decision == EvolutionDecision.DENY

    @pytest.mark.asyncio
    async def test_handler_receives_correct_suggestion(self) -> None:
        received: list[PolicySuggestion] = []

        async def handler(s: PolicySuggestion) -> EvolutionDecision:
            received.append(s)
            return EvolutionDecision.DENY

        engine = PolicyEvolutionEngine(handler=handler)
        suggestion = PolicySuggestion(
            category=DenialCategory.SCOPE_VIOLATION,
            tool="navigate",
            description='Add domain "example.com"?',
            change={"type": "widen_scope", "tool": "navigate", "field": "domains", "add": ["example.com"]},
        )
        await engine.evolve(suggestion)
        assert len(received) == 1
        assert received[0].tool == "navigate"
        assert received[0].category == DenialCategory.SCOPE_VIOLATION


# ---------------------------------------------------------------------------
# apply_change
# ---------------------------------------------------------------------------

@dataclass
class FakePolicy:
    enabled_actions: list[str] = field(default_factory=list)
    scope: dict[str, list[str]] = field(default_factory=dict)
    forbidden_patterns: list[str] = field(default_factory=list)


class TestApplyChange:
    def test_add_capability(self) -> None:
        engine = PolicyEvolutionEngine()
        policy = FakePolicy()
        suggestion = PolicySuggestion(
            category=DenialCategory.NO_CAPABILITY,
            tool="click",
            description="Add click?",
            change={"type": "add_capability", "tool": "click", "scope": {}},
        )
        engine.apply_change(suggestion, policy)
        assert "click" in policy.enabled_actions

    def test_add_capability_idempotent(self) -> None:
        engine = PolicyEvolutionEngine()
        policy = FakePolicy(enabled_actions=["click"])
        suggestion = PolicySuggestion(
            category=DenialCategory.NO_CAPABILITY,
            tool="click",
            description="Add click?",
            change={"type": "add_capability", "tool": "click", "scope": {}},
        )
        engine.apply_change(suggestion, policy)
        assert policy.enabled_actions.count("click") == 1

    def test_widen_scope(self) -> None:
        engine = PolicyEvolutionEngine()
        policy = FakePolicy()
        suggestion = PolicySuggestion(
            category=DenialCategory.SCOPE_VIOLATION,
            tool="navigate",
            description="Add domain?",
            change={"type": "widen_scope", "tool": "navigate", "field": "domains", "add": ["example.com"]},
        )
        engine.apply_change(suggestion, policy)
        assert "example.com" in policy.scope["domains"]

    def test_remove_forbidden(self) -> None:
        engine = PolicyEvolutionEngine()
        policy = FakePolicy(forbidden_patterns=["rm -rf", "del /s"])
        suggestion = PolicySuggestion(
            category=DenialCategory.FORBIDDEN_MATCH,
            tool="execute",
            description="Remove rm -rf?",
            change={"type": "remove_forbidden", "pattern": "rm -rf"},
        )
        engine.apply_change(suggestion, policy)
        assert "rm -rf" not in policy.forbidden_patterns
        assert "del /s" in policy.forbidden_patterns

    def test_apply_to_policy_without_matching_attr(self) -> None:
        """apply_change should not crash if policy lacks the expected attribute."""
        engine = PolicyEvolutionEngine()
        policy = object()  # No enabled_actions, scope, or forbidden_patterns
        suggestion = PolicySuggestion(
            category=DenialCategory.NO_CAPABILITY,
            tool="click",
            description="Add click?",
            change={"type": "add_capability", "tool": "click", "scope": {}},
        )
        # Should not raise
        engine.apply_change(suggestion, policy)

    def test_widen_scope_idempotent(self) -> None:
        engine = PolicyEvolutionEngine()
        policy = FakePolicy(scope={"domains": ["example.com"]})
        suggestion = PolicySuggestion(
            category=DenialCategory.SCOPE_VIOLATION,
            tool="navigate",
            description="Add domain?",
            change={"type": "widen_scope", "tool": "navigate", "field": "domains", "add": ["example.com"]},
        )
        engine.apply_change(suggestion, policy)
        assert policy.scope["domains"].count("example.com") == 1
