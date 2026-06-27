"""Hermetic desktop integration tests — Batch 7.

Exercises the real ``DesktopAgent.execute()`` stack through mock surfaces.
No real hardware, no ``--run-integration`` flag, no LLM required.

Coverage that smoke tests do NOT already provide:
  - Runtime execution receipts (success + read-only no-side-effects)
  - Policy-deny behavior through real ``DesktopAgent.execute()``
  - No-adapter-call assertions on dry-run and policy-deny
  - CLI command-layer goal capture (Batch 4 capability routing)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from deskaoy.desktop_agent import DesktopAgent
from deskaoy.os_types import (
    AgentContext,
    AgentGoal,
    AgentResult,
    Confidence,
    ErrorCode,
    ResultStatus,
)
from deskaoy.policy import PolicyBridge, PolicyDecision, PolicyEffect
from deskaoy.results.types import ActionResult, ResultMeta
from deskaoy.safety.policy_evolution import (
    EvolutionDecision,
    PolicyEvolutionEngine,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_surface():
    """Build a mock surface with AsyncMock methods so we can assert calls."""
    surface = AsyncMock()
    surface.name = "mock-surface"
    surface.click = AsyncMock(return_value=ActionResult(
        ok=True, data={"clicked": True},
        meta=ResultMeta(trace_id="test", duration_ms=10),
    ))
    surface.fill = AsyncMock(return_value=ActionResult(
        ok=True, data={"filled": True},
        meta=ResultMeta(trace_id="test", duration_ms=20),
    ))
    surface.screenshot = AsyncMock(return_value=ActionResult(
        ok=True, data={"screenshot": b"\x89PNG"},
        meta=ResultMeta(trace_id="test", duration_ms=5),
    ))
    surface.snapshot = AsyncMock(return_value=ActionResult(
        ok=True, data={"tree": []},
        meta=ResultMeta(trace_id="test", duration_ms=15),
    ))
    surface.type_text = AsyncMock(return_value=ActionResult(ok=True))
    surface.key_press = AsyncMock(return_value=ActionResult(ok=True))
    surface.scroll = AsyncMock(return_value=ActionResult(ok=True))
    surface.evaluate = AsyncMock(return_value=ActionResult(ok=True))
    surface.current_url = AsyncMock(return_value="about:blank")
    surface.current_title = AsyncMock(return_value="Mock")
    return surface


def _make_context(**overrides) -> AgentContext:
    defaults = {
        "execution_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "task_id": str(uuid.uuid4()),
        "user_id": "integration-test",
        "session_id": str(uuid.uuid4()),
        "timeout_seconds": 10,
        "dry_run": False,
    }
    defaults.update(overrides)
    return AgentContext(**defaults)


def _deny_bridge() -> PolicyBridge:
    """A PolicyBridge whose preflight always DENYs."""
    async def _deny(perms, ctx):  # noqa: ARG001
        return PolicyDecision(
            effect=PolicyEffect.DENY,
            reason="Integration test: denied",
            policy_decision_id="test-deny-001",
        )
    return PolicyBridge(preflight_fn=_deny, dev_mode=False)


# ---------------------------------------------------------------------------
# A. Dry-run execution path
# ---------------------------------------------------------------------------

class TestDryRunExecution:

    @pytest.mark.asyncio
    async def test_dry_run_click_returns_dry_run_status(self):
        agent = DesktopAgent(surface=_mock_surface())
        goal = AgentGoal(capability="click", params={"target": "button"})
        ctx = _make_context(dry_run=True)

        result = await agent.execute(goal, ctx)

        assert result.status == ResultStatus.DRY_RUN
        assert result.data["simulated"] is True
        assert result.metadata["dry_run"] is True

    @pytest.mark.asyncio
    async def test_dry_run_does_not_call_adapter(self):
        surface = _mock_surface()
        agent = DesktopAgent(surface=surface)
        goal = AgentGoal(capability="click", params={"target": "button"})
        ctx = _make_context(dry_run=True)

        await agent.execute(goal, ctx)

        surface.click.assert_not_called()


# ---------------------------------------------------------------------------
# B. Policy-deny path
# ---------------------------------------------------------------------------

class TestPolicyDenyExecution:

    @pytest.mark.asyncio
    async def test_policy_deny_blocks_execution(self):
        agent = DesktopAgent(
            surface=_mock_surface(),
            policy_bridge=_deny_bridge(),
        )
        goal = AgentGoal(capability="click", params={"target": "button"})
        ctx = _make_context()

        result = await agent.execute(goal, ctx)

        assert result.status == ResultStatus.FAILURE
        assert result.confidence.score == 0.0
        assert any(i.code == ErrorCode.PERMISSION_DENIED for i in result.issues)

    @pytest.mark.asyncio
    async def test_policy_deny_adapter_not_called(self):
        surface = _mock_surface()
        agent = DesktopAgent(
            surface=surface,
            policy_bridge=_deny_bridge(),
        )
        goal = AgentGoal(capability="click", params={"target": "button"})
        ctx = _make_context()

        await agent.execute(goal, ctx)

        surface.click.assert_not_called()

    @pytest.mark.asyncio
    async def test_policy_allow_once_executes(self):
        """ALLOW_ONCE override from policy evolution lets execution proceed.

        The deny reason must contain "blocked by policy" so the suggestion
        engine proposes a policy change, which the handler then allows.
        """

        async def _allow_once(suggestion):  # noqa: ARG001
            return EvolutionDecision.ALLOW_ONCE

        async def _deny_with_suggestible_reason(perms, ctx):  # noqa: ARG001
            return PolicyDecision(
                effect=PolicyEffect.DENY,
                reason="Action blocked by policy: test override",
                policy_decision_id="test-deny-allow-once",
            )

        bridge = PolicyBridge(
            preflight_fn=_deny_with_suggestible_reason,
            dev_mode=False,
        )
        agent = DesktopAgent(
            surface=_mock_surface(),
            policy_bridge=bridge,
        )
        agent._policy_evolution = PolicyEvolutionEngine(handler=_allow_once)

        goal = AgentGoal(capability="click", params={"target": "button"})
        ctx = _make_context()

        result = await agent.execute(goal, ctx)

        assert result.status == ResultStatus.SUCCESS
        agent._surface.click.assert_awaited_once()


# ---------------------------------------------------------------------------
# C. Real execution through mock surface (receipts)
# ---------------------------------------------------------------------------

class TestRealExecutionReceipts:

    @pytest.mark.asyncio
    async def test_click_success_produces_receipt(self):
        agent = DesktopAgent(surface=_mock_surface())
        goal = AgentGoal(capability="click", params={"target": "button"})
        ctx = _make_context()

        result = await agent.execute(goal, ctx)

        assert result.status == ResultStatus.SUCCESS
        receipt = result.data["receipt"]
        assert receipt["runtime_execution_performed"] is True
        assert receipt["attempt_state"] == "completed"

    @pytest.mark.asyncio
    async def test_screenshot_receipt_has_no_side_effects(self):
        agent = DesktopAgent(surface=_mock_surface())
        goal = AgentGoal(capability="screenshot", params={})
        ctx = _make_context()

        result = await agent.execute(goal, ctx)

        assert result.status == ResultStatus.SUCCESS
        receipt = result.data["receipt"]
        assert receipt["runtime_execution_performed"] is True
        assert receipt["side_effects_performed"] is False

    @pytest.mark.asyncio
    async def test_estimate_returns_cost_and_confidence(self):
        agent = DesktopAgent(surface=_mock_surface())
        goal = AgentGoal(capability="click", params={"target": "button"})
        ctx = _make_context()

        estimate = await agent.estimate(goal, ctx)

        assert estimate.can_execute is True
        assert estimate.confidence.score > 0
        assert estimate.latency_ms > 0


# ---------------------------------------------------------------------------
# D. CLI command-layer
# ---------------------------------------------------------------------------

class TestCLICommandLayer:

    def test_cli_execute_dry_run_returns_zero(self):
        from deskaoy.cli.main import main

        with patch("deskaoy.cli.main._get_agent", return_value=DesktopAgent(surface=_mock_surface())):
            code = main(["execute", "--dry-run", "click OK"])

        assert code == 0

    def test_cli_execute_capability_click_routes_correctly(self):
        """The CLI must build the correct AgentGoal for --capability click."""
        from deskaoy.cli.main import main

        captured_goal = {}

        async def fake_execute(goal, ctx):  # noqa: ARG001
            captured_goal["capability"] = goal.capability
            captured_goal["params"] = goal.params
            return AgentResult(
                execution_id="test",
                status=ResultStatus.SUCCESS,
                summary="mock",
                confidence=Confidence(score=1.0, reason="test"),
            )

        agent = DesktopAgent(surface=_mock_surface())
        agent.execute = fake_execute

        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            main(["execute", "--dry-run", "--capability", "click", "button"])

        assert captured_goal["capability"] == "click"
        assert captured_goal["params"] == {"target": "button"}
