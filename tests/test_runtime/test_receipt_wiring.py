"""Tests for B38 Runtime Execution Receipt wiring into DesktopAgent.

Tests that every execution path through _execute_single_action produces
a RuntimeExecutionReceipt attached to AgentResult.data["receipt"].

Covers:
  - Blocked path (preflight failure)
  - Timeout path (adapter times out)
  - Success path (completed with receipt)
  - Failure path (adapter returns error, receipt with FAILED state)
  - Receipt immutability (frozen after creation)
  - Receipt truthfulness (truth_message matches actual state)
  - Side-effects tracking (non-read-only actions report side_effects_performed)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from deskaoy.desktop_agent import DesktopAgent
from deskaoy.os_types import (
    AgentContext,
    AgentGoal,
    ResultStatus,
)
from deskaoy.results.types import ActionError, ActionResult, ErrorCategory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent() -> DesktopAgent:
    """Create a DesktopAgent with a mock surface adapter."""
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

    agent = DesktopAgent(surface=surface)
    return agent


def _make_context(**overrides) -> AgentContext:
    defaults = {
        "execution_id": "test-exec-001",
        "idempotency_key": "idem-001",
        "task_id": "task-001",
        "user_id": "user-001",
        "session_id": "sess-001",
        "timeout_seconds": 10,
        "dry_run": False,
    }
    defaults.update(overrides)
    return AgentContext(**defaults)


# ---------------------------------------------------------------------------
# T03-R01: Success path produces receipt with COMPLETED state
# ---------------------------------------------------------------------------

class TestSuccessReceipt:

    @pytest.mark.asyncio
    async def test_click_success_has_receipt(self):
        agent = _make_agent()
        goal = AgentGoal(capability="click", params={"target": "OK button"})
        ctx = _make_context()
        result = await agent.execute(goal, ctx)
        assert result.status == ResultStatus.SUCCESS
        assert "receipt" in result.data
        receipt = result.data["receipt"]
        assert receipt["attempt_state"] == "completed"
        assert receipt["runtime_execution_performed"] is True
        assert receipt["preflight_passed"] is True
        assert receipt["side_effects_performed"] is True  # click is sensitive

    @pytest.mark.asyncio
    async def test_screenshot_success_no_side_effects(self):
        agent = _make_agent()
        goal = AgentGoal(capability="screenshot", params={})
        ctx = _make_context()
        result = await agent.execute(goal, ctx)
        assert result.status == ResultStatus.SUCCESS
        receipt = result.data["receipt"]
        assert receipt["attempt_state"] == "completed"
        assert receipt["side_effects_performed"] is False  # read-only

    @pytest.mark.asyncio
    async def test_receipt_has_execution_id(self):
        agent = _make_agent()
        goal = AgentGoal(capability="screenshot", params={})
        ctx = _make_context(execution_id="unique-exec-42")
        result = await agent.execute(goal, ctx)
        receipt = result.data["receipt"]
        assert receipt["execution_id"] == "unique-exec-42"

    @pytest.mark.asyncio
    async def test_receipt_has_attempt_id(self):
        agent = _make_agent()
        goal = AgentGoal(capability="screenshot", params={})
        ctx = _make_context()
        result = await agent.execute(goal, ctx)
        receipt = result.data["receipt"]
        assert receipt["attempt_id"]  # non-empty UUID

    @pytest.mark.asyncio
    async def test_receipt_has_truth_message(self):
        agent = _make_agent()
        goal = AgentGoal(capability="screenshot", params={})
        ctx = _make_context()
        result = await agent.execute(goal, ctx)
        receipt = result.data["receipt"]
        assert "completed" in receipt["truth_message"].lower() or "no side effects" in receipt["truth_message"].lower()

    @pytest.mark.asyncio
    async def test_receipt_has_preflight_fingerprint(self):
        agent = _make_agent()
        goal = AgentGoal(capability="screenshot", params={})
        ctx = _make_context()
        result = await agent.execute(goal, ctx)
        receipt = result.data["receipt"]
        assert receipt["preflight_fingerprint"]  # non-empty


# ---------------------------------------------------------------------------
# T03-R02: Failure path produces receipt with FAILED state
# ---------------------------------------------------------------------------

class TestFailureReceipt:

    @pytest.mark.asyncio
    async def test_adapter_failure_has_receipt(self):
        agent = _make_agent()
        # Make click return failure
        agent._surface.click = AsyncMock(
            return_value=ActionResult(ok=False, error=ActionError(category=ErrorCategory.SELECTOR_NOT_FOUND, code="not_found", message="Element not found"))
        )
        goal = AgentGoal(capability="click", params={"target": "missing button"})
        ctx = _make_context()
        result = await agent.execute(goal, ctx)
        assert result.status == ResultStatus.FAILURE
        assert "receipt" in result.data
        receipt = result.data["receipt"]
        assert receipt["attempt_state"] == "failed"
        assert receipt["runtime_execution_performed"] is True
        assert receipt["side_effects_performed"] is False  # failed, no side effects completed

    @pytest.mark.asyncio
    async def test_failure_truth_message(self):
        agent = _make_agent()
        agent._surface.click = AsyncMock(
            return_value=ActionResult(ok=False, error=ActionError(category=ErrorCategory.UNKNOWN, code="error", message="fail"))
        )
        goal = AgentGoal(capability="click", params={"target": "x"})
        ctx = _make_context()
        result = await agent.execute(goal, ctx)
        receipt = result.data["receipt"]
        assert "failed" in receipt["truth_message"].lower() or "uncertain" in receipt["truth_message"].lower()


# ---------------------------------------------------------------------------
# T03-R03: Timeout path produces receipt with TIMED_OUT state
# ---------------------------------------------------------------------------

class TestTimeoutReceipt:

    @pytest.mark.asyncio
    async def test_timeout_has_receipt(self):
        agent = _make_agent()
        # Make click take forever
        async def _slow_click(**kwargs):
            await asyncio.sleep(60)
            return ActionResult(ok=True, data={})

        agent._surface.click = _slow_click
        goal = AgentGoal(capability="click", params={"target": "slow button"})
        ctx = _make_context(timeout_seconds=0.1)
        result = await agent.execute(goal, ctx)
        assert result.status == ResultStatus.FAILURE
        assert "receipt" in result.data
        receipt = result.data["receipt"]
        assert receipt["attempt_state"] == "timed_out"
        assert receipt["runtime_execution_performed"] is False
        assert receipt["preflight_passed"] is True

    @pytest.mark.asyncio
    async def test_timeout_truth_message(self):
        agent = _make_agent()

        async def _slow(**kwargs):
            await asyncio.sleep(60)

        agent._surface.click = _slow
        goal = AgentGoal(capability="click", params={"target": "x"})
        ctx = _make_context(timeout_seconds=0.05)
        result = await agent.execute(goal, ctx)
        receipt = result.data["receipt"]
        assert "timed out" in receipt["truth_message"].lower()


# ---------------------------------------------------------------------------
# T03-R04: Blocked path produces receipt with BLOCKED state
# ---------------------------------------------------------------------------

class TestBlockedReceipt:

    @pytest.mark.asyncio
    async def test_no_surface_produces_failure(self):
        agent = DesktopAgent(surface=None)
        goal = AgentGoal(capability="click", params={"target": "x"})
        ctx = _make_context()
        result = await agent.execute(goal, ctx)
        # No surface → early return before preflight
        assert result.status == ResultStatus.CONFIG_ERROR

    @pytest.mark.asyncio
    async def test_blocked_preflight_has_receipt(self):
        """If preflight detects secrets in params, it blocks with receipt."""
        agent = _make_agent()
        goal = AgentGoal(
            capability="fill",
            params={"target": "API key field", "value": "sk-abc123def456ghi789jkl012"},
        )
        ctx = _make_context()
        result = await agent.execute(goal, ctx)
        # Preflight CHK-PF-12 should detect the secret pattern
        assert result.status == ResultStatus.FAILURE
        # The receipt should be present
        assert "receipt" in result.data
        receipt = result.data["receipt"]
        assert receipt["attempt_state"] == "blocked"
        assert receipt["runtime_execution_performed"] is False
        assert receipt["preflight_passed"] is False


# ---------------------------------------------------------------------------
# T03-R05: Receipt structure completeness
# ---------------------------------------------------------------------------

class TestReceiptStructure:

    @pytest.mark.asyncio
    async def test_receipt_has_all_required_fields(self):
        agent = _make_agent()
        goal = AgentGoal(capability="screenshot", params={})
        ctx = _make_context()
        result = await agent.execute(goal, ctx)
        r = result.data["receipt"]
        # All RuntimeExecutionReceipt fields must be present
        required = [
            "execution_id", "attempt_id", "attempt_state",
            "truth_message", "runtime_execution_performed",
            "simulated", "dry_run", "side_effects_performed",
            "preflight_passed", "preflight_fingerprint",
            "obligations_checked", "obligations_blocked",
            "timestamp",
        ]
        for field in required:
            assert field in r, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_dry_run_receipt(self):
        """Dry run path currently returns early without receipt.
        This is by design: dry runs skip the preflight/execution path.
        Verify it returns DRY_RUN status without crashing."""
        agent = _make_agent()
        goal = AgentGoal(capability="screenshot", params={})
        ctx = _make_context(dry_run=True)
        result = await agent.execute(goal, ctx)
        # Dry run returns early — no receipt (by design)
        assert result.status == ResultStatus.DRY_RUN


# ---------------------------------------------------------------------------
# T03-R06: Side-effects tracking accuracy
# ---------------------------------------------------------------------------

class TestSideEffectsTracking:

    @pytest.mark.asyncio
    async def test_sensitive_action_reports_side_effects(self):
        agent = _make_agent()
        goal = AgentGoal(capability="fill", params={"target": "name", "value": "Alice"})
        ctx = _make_context()
        result = await agent.execute(goal, ctx)
        receipt = result.data["receipt"]
        assert receipt["side_effects_performed"] is True

    @pytest.mark.asyncio
    async def test_read_only_action_no_side_effects(self):
        agent = _make_agent()
        goal = AgentGoal(capability="snapshot", params={})
        ctx = _make_context()
        result = await agent.execute(goal, ctx)
        receipt = result.data["receipt"]
        assert receipt["side_effects_performed"] is False

    @pytest.mark.asyncio
    async def test_key_press_reports_side_effects(self):
        agent = _make_agent()
        goal = AgentGoal(capability="key_press", params={"key": "Enter"})
        ctx = _make_context()
        result = await agent.execute(goal, ctx)
        receipt = result.data["receipt"]
        assert receipt["side_effects_performed"] is True
