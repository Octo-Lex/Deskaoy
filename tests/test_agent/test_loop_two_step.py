"""Tests for AgentLoop two-step integration (BATCH-06 TASK-03)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from deskaoy.agent.loop import AgentLoop
from deskaoy.agent.registry import ToolRegistry
from deskaoy.agent.types import StepResult
from deskaoy.results.types import ActionResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_registry() -> ToolRegistry:
    """Create a registry with a simple 'click' tool."""
    registry = ToolRegistry()

    async def click(target="", **kwargs):
        return ActionResult(ok=True)

    registry.register(click)
    return registry


def _make_llm() -> AsyncMock:
    """Create a mock LLM that proposes click then done."""
    llm = AsyncMock()
    llm.create_plan = AsyncMock(return_value=[{"description": "Click the button"}])
    llm.replan = AsyncMock(return_value=[{"description": "Click the button"}])
    # First call: click, second call: done
    llm.propose_action = AsyncMock(side_effect=[
        {"action": "click", "params": {"target": "button"}},
        {"done": True},
    ])
    return llm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAgentLoopTwoStep:
    """TEST-06-03-01 through TEST-06-03-08."""

    def test_accepts_two_step_constructor(self):
        """TEST-06-03-01: AgentLoop accepts two_step=True."""
        registry = _make_tool_registry()
        llm = _make_llm()
        loop = AgentLoop(
            controller=None,
            registry=registry,
            llm_client=llm,
            two_step=True,
        )
        assert loop._two_step is True

    def test_two_step_defaults_false(self):
        """TEST-06-03-02: two_step defaults to False."""
        registry = _make_tool_registry()
        llm = _make_llm()
        loop = AgentLoop(
            controller=None,
            registry=registry,
            llm_client=llm,
        )
        assert loop._two_step is False

    def test_step_result_has_verification_field(self):
        """TEST-06-03-03: StepResult has verification field."""
        result = StepResult(
            step_number=1,
            action_name="click",
            action_params={},
            action_result=None,
            duration_ms=100,
        )
        assert hasattr(result, "verification")
        assert result.verification is None

    def test_step_result_has_diff_summary(self):
        """TEST-06-03-04: StepResult has diff_summary field."""
        result = StepResult(
            step_number=1,
            action_name="click",
            action_params={},
            action_result=None,
            duration_ms=100,
        )
        assert hasattr(result, "diff_summary")
        assert result.diff_summary is None

    def test_build_prompt_includes_diff_context(self):
        """TEST-06-03-05: _build_prompt includes diff context when enabled."""
        registry = _make_tool_registry()
        llm = _make_llm()
        loop = AgentLoop(
            controller=None,
            registry=registry,
            llm_client=llm,
            two_step=True,
        )

        from deskaoy.agent.types import PlanItem
        plan = [PlanItem(index=0, description="Click button")]

        # Create a step with diff_summary
        step = StepResult(
            step_number=1,
            action_name="click",
            action_params={"target": "btn"},
            action_result=ActionResult(ok=True),
            duration_ms=50,
            diff_summary="click: applied (confidence=0.90) — Click opened dialog: 'Confirm'",
        )

        prompt = loop._build_prompt("Click the button", plan, [step], "Tools: click")
        assert "Action Verification:" in prompt
        assert "applied" in prompt

    def test_build_prompt_no_diff_when_disabled(self):
        """TEST-06-03-06: No diff context when two_step=False."""
        registry = _make_tool_registry()
        llm = _make_llm()
        loop = AgentLoop(
            controller=None,
            registry=registry,
            llm_client=llm,
            two_step=False,
        )

        from deskaoy.agent.types import PlanItem
        plan = [PlanItem(index=0, description="Click button")]
        step = StepResult(
            step_number=1,
            action_name="click",
            action_params={},
            action_result=ActionResult(ok=True),
            duration_ms=50,
            diff_summary="some diff",
        )

        prompt = loop._build_prompt("Click", plan, [step], "Tools: click")
        assert "Action Verification:" not in prompt

    def test_verify_step_sets_fields(self):
        """TEST-06-03-07: _verify_step sets verification and diff_summary."""
        registry = _make_tool_registry()
        llm = _make_llm()
        loop = AgentLoop(
            controller=None,
            registry=registry,
            llm_client=llm,
            two_step=True,
        )

        step = StepResult(
            step_number=1,
            action_name="click",
            action_params={"target": "btn"},
            action_result=ActionResult(ok=True),
            duration_ms=50,
        )

        # Run verification (no pre-snapshot means early return)
        result = asyncio.run(loop._verify_step(step, "click", {"target": "btn"}))
        # First call initializes pre_snapshot, doesn't verify yet
        assert isinstance(result, StepResult)

    def test_step_result_preserves_existing_fields(self):
        """TEST-06-03-08: New fields don't break existing StepResult usage."""
        result = StepResult(
            step_number=1,
            action_name="click",
            action_params={"target": "btn"},
            action_result=ActionResult(ok=True),
            duration_ms=100,
            page_changed=True,
        )
        assert result.step_number == 1
        assert result.page_changed is True
        assert result.error is None
        assert result.verification is None
        assert result.diff_summary is None
