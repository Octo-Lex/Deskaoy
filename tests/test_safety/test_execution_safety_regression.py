"""Regression tests for Batch 3 execution-safety fixes.

Covers two P0 safety bugs that were fixed in ``_execute_single_action``:

1. **Sanitized params discarded** — ``validate_action()`` produced
   ``sanitized_params`` (type-coerced, defaults applied, spec-filtered),
   but the code immediately overwrote them with ``dict(goal.params)``
   before adapter dispatch. The adapter therefore received raw, un-coerced
   request parameters.

2. **Policy-deny fallthrough** — after policy self-evolution failed to
   lift a denial, the branch executed ``pass`` and fell through to normal
   execution. This created an accidental allow path through a safety gate
   on an agent that injects keyboard/mouse input.

Tests assert the *behavior* (what the adapter receives / whether it is
called), not the implementation, so they survive refactors of the
surrounding code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from deskaoy.desktop_agent import DesktopAgent
from deskaoy.os_types import (
    AgentContext,
    AgentGoal,
    ErrorCode,
    ResultStatus,
)
from deskaoy.policy import PolicyBridge, PolicyDecision, PolicyEffect
from deskaoy.results.types import ActionResult
from deskaoy.safety.policy_evolution import (
    EvolutionDecision,
    PolicyEvolutionEngine,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_agent(*, policy_bridge: PolicyBridge | None = None) -> DesktopAgent:
    """Build a DesktopAgent backed by a mock surface adapter.

    The mock records the exact kwargs each adapter method was called with so
    tests can assert on what was dispatched.
    """
    surface = AsyncMock()
    surface.name = "mock-surface"
    surface.click = AsyncMock(return_value=ActionResult(ok=True, data={"clicked": True}))
    surface.fill = AsyncMock(return_value=ActionResult(ok=True, data={"filled": True}))
    surface.screenshot = AsyncMock(return_value=ActionResult(ok=True, data={"screenshot": b"\x89PNG"}))
    surface.snapshot = AsyncMock(return_value=ActionResult(ok=True, data={"tree": []}))
    surface.key_press = AsyncMock(return_value=ActionResult(ok=True, data={"pressed": True}))
    surface.scroll = AsyncMock(return_value=ActionResult(ok=True, data={"scrolled": True}))
    surface.type_text = AsyncMock(return_value=ActionResult(ok=True, data={"typed": True}))
    surface.evaluate = AsyncMock(return_value=ActionResult(ok=True, data={"result": None}))
    surface.current_url = AsyncMock(return_value="about:blank")
    surface.current_title = AsyncMock(return_value="Mock")

    agent = DesktopAgent(surface=surface, policy_bridge=policy_bridge)
    return agent


def _make_context(**overrides) -> AgentContext:
    defaults = {
        "execution_id": "safety-regression-001",
        "idempotency_key": "idem-001",
        "task_id": "task-001",
        "user_id": "user-001",
        "session_id": "sess-001",
        "timeout_seconds": 10,
        "dry_run": False,
    }
    defaults.update(overrides)
    return AgentContext(**defaults)


def _denying_bridge(reason: str = "Action blocked by policy: test denial") -> PolicyBridge:
    """A PolicyBridge whose preflight always DENYs with a suggestible reason.

    The reason text contains "blocked by policy" so ``suggest_policy_change``
    returns a SCOPE_VIOLATION suggestion (i.e. evolution is attempted rather
    than hard-denied).
    """
    async def _deny(perms, ctx):  # noqa: ARG001
        return PolicyDecision(
            effect=PolicyEffect.DENY,
            reason=reason,
            policy_decision_id="test-deny-001",
        )

    return PolicyBridge(preflight_fn=_deny, dev_mode=False)


def _evolution_engine(decision: EvolutionDecision) -> PolicyEvolutionEngine:
    """An evolution engine whose ``evolve()`` always returns *decision*."""
    async def _handler(suggestion):  # noqa: ARG001
        return decision

    return PolicyEvolutionEngine(handler=_handler)


# ---------------------------------------------------------------------------
# Patch 1 — sanitized params reach the adapter
# ---------------------------------------------------------------------------

class TestSanitizedParamsReachAdapter:

    @pytest.mark.asyncio
    async def test_coerced_params_dispatched_not_raw(self):
        """``num_clicks="2"`` (str) is coerced to ``2`` (int) by the validator.

        Before the fix the adapter received the raw string ``"2"``; after the
        fix it receives the sanitized int ``2``.
        """
        agent = _make_agent()
        goal = AgentGoal(
            capability="click",
            params={"target": "OK button", "num_clicks": "2"},
        )
        ctx = _make_context()

        result = await agent.execute(goal, ctx)

        assert result.status == ResultStatus.SUCCESS
        agent._surface.click.assert_awaited_once()
        # The discriminating field: must be the coerced int, not the raw str.
        assert agent._surface.click.call_args.kwargs["num_clicks"] == 2
        assert isinstance(
            agent._surface.click.call_args.kwargs["num_clicks"], int
        )

    @pytest.mark.asyncio
    async def test_stringified_numeric_coord_is_coerced(self):
        """A stringified coordinate must arrive at the adapter as a number."""
        agent = _make_agent()
        goal = AgentGoal(
            capability="click",
            params={"x": "100", "y": "200"},
        )
        ctx = _make_context()

        await agent.execute(goal, ctx)

        kwargs = agent._surface.click.call_args.kwargs
        assert kwargs["x"] == 100
        assert isinstance(kwargs["x"], int)
        assert kwargs["y"] == 200


# ---------------------------------------------------------------------------
# Patch 2 — policy denial must never fall through to execution
# ---------------------------------------------------------------------------

class TestPolicyDenyFallthrough:

    @pytest.mark.asyncio
    async def test_deny_with_no_suggestion_blocks_execution(self):
        """A denial that yields no evolution suggestion must hard-stop.

        Uses the disabled-actions guard, whose reason is not suggestible.
        """
        bridge = PolicyBridge(dev_mode=True, disabled_actions={"click"})
        agent = _make_agent(policy_bridge=bridge)

        goal = AgentGoal(capability="click", params={"target": "btn"})
        ctx = _make_context()

        result = await agent.execute(goal, ctx)

        assert result.status == ResultStatus.FAILURE
        assert agent._surface.click.call_count == 0
        assert any(issue.code == ErrorCode.PERMISSION_DENIED for issue in result.issues)

    @pytest.mark.asyncio
    async def test_deny_after_failed_evolution_does_not_execute(self):
        """The critical regression: evolution re-check still denies.

        Before the fix this path fell through via an empty ``pass`` and the
        adapter was invoked despite the policy remaining DENY.
        """
        agent = _make_agent(policy_bridge=_denying_bridge())
        # evolve() returns ADD_TO_POLICY, but the bridge still denies on
        # re-check → must hard-stop, not fall through.
        agent._policy_evolution = _evolution_engine(EvolutionDecision.ADD_TO_POLICY)

        goal = AgentGoal(capability="click", params={"target": "btn"})
        ctx = _make_context()

        result = await agent.execute(goal, ctx)

        # Three-part contract per reviewer gate 3:
        assert result.status == ResultStatus.FAILURE
        # The safety-critical assertion: adapter never invoked.
        assert agent._surface.click.call_count == 0
        # Contract assertion: this is a policy block, not generic failure.
        assert any(issue.code == ErrorCode.PERMISSION_DENIED for issue in result.issues)

    @pytest.mark.asyncio
    async def test_deny_user_keeps_denial_blocks_execution(self):
        """When the user (handler) declines to evolve, execution is blocked."""
        agent = _make_agent(policy_bridge=_denying_bridge())
        agent._policy_evolution = _evolution_engine(EvolutionDecision.DENY)

        goal = AgentGoal(capability="click", params={"target": "btn"})
        ctx = _make_context()

        result = await agent.execute(goal, ctx)

        # Three-part contract per reviewer gate 3:
        assert result.status == ResultStatus.FAILURE
        assert agent._surface.click.call_count == 0
        assert any(issue.code == ErrorCode.PERMISSION_DENIED for issue in result.issues)

    @pytest.mark.asyncio
    async def test_allow_once_override_executes_adapter(self):
        """ALLOW_ONCE is an explicit override that *does* reach execution.

        Guards against over-fixing: the override path must still work.
        """
        agent = _make_agent(policy_bridge=_denying_bridge())
        agent._policy_evolution = _evolution_engine(EvolutionDecision.ALLOW_ONCE)

        goal = AgentGoal(capability="click", params={"target": "btn"})
        ctx = _make_context()

        result = await agent.execute(goal, ctx)

        assert result.status == ResultStatus.SUCCESS
        agent._surface.click.assert_awaited_once()
