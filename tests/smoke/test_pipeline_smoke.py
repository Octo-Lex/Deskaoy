"""Pipeline smoke tests — validate full DesktopAgent lifecycle without hardware.

These tests exercise every major execution path end-to-end using mock
surface adapters. They run fast (no I/O) and catch wiring regressions
that unit tests might miss.

Run: pytest tests/smoke/ -v
"""


import pytest

from deskaoy.desktop_agent import DesktopAgent
from deskaoy.os_types import (
    AgentContext,
    AgentGoal,
    RestoreMethod,
    ResultStatus,
    Snapshot,
)
from deskaoy.results.types import ActionResult, ResultMeta


def _snapshot(**overrides) -> Snapshot:
    """Build a Snapshot with sensible defaults."""
    defaults = dict(
        snapshot_id="snap-001",
        execution_id="exec-001",
        resource_type="desktop_surface",
        resource_id="window-1",
        before_state=None,
        after_state=None,
        restore_method=RestoreMethod.NONE,
        state_version="1",
        created_at="2025-01-01T00:00:00Z",
        expires_at="2025-12-31T23:59:59Z",
    )
    defaults.update(overrides)
    return Snapshot(**defaults)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockSurface:
    """Minimal mock surface that satisfies DesktopAgent's expectations."""

    def __init__(self):
        self._title = "MockWindow"
        self._url = "mock://test"

    async def click(self, target="", **kw):
        return ActionResult(
            ok=True, data={"clicked": target},
            meta=ResultMeta(trace_id='test', duration_ms=10),
        )

    async def fill(self, target="", value="", **kw):
        return ActionResult(
            ok=True, data={"filled": value},
            meta=ResultMeta(trace_id='test', duration_ms=20),
        )

    async def type_text(self, text="", **kw):
        return ActionResult(
            ok=True, data={"typed": text},
            meta=ResultMeta(trace_id='test', duration_ms=30),
        )

    async def key_press(self, key="", **kw):
        return ActionResult(
            ok=True, data={"key": key},
            meta=ResultMeta(trace_id='test', duration_ms=5),
        )

    async def scroll(self, direction="down", amount=300, **kw):
        return ActionResult(
            ok=True, data={"scrolled": direction},
            meta=ResultMeta(trace_id='test', duration_ms=15),
        )

    async def screenshot(self, **kw):
        return ActionResult(
            ok=True, data={"screenshot": "mock_png"},
            meta=ResultMeta(trace_id='test', duration_ms=50),
        )

    async def snapshot(self, **kw):
        return ActionResult(
            ok=True, data={"ax_tree": "<root />"},
            meta=ResultMeta(trace_id='test', duration_ms=40),
        )

    def current_title(self):
        return self._title

    def current_url(self):
        return self._url


def _make_context(**overrides) -> AgentContext:
    defaults = dict(
        execution_id="smoke-test-001",
        idempotency_key="idem-001",
        task_id="task-001",
        user_id="tester",
        session_id="session-001",
    )
    defaults.update(overrides)
    return AgentContext(**defaults)


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------

class TestExecuteLifecycle:
    """Full execute → estimate → undo → compensate lifecycle."""

    @pytest.mark.asyncio
    async def test_execute_click(self):
        agent = DesktopAgent(surface=MockSurface())
        goal = AgentGoal(capability="click", params={"target": "Submit"})
        result = await agent.execute(goal, _make_context())
        assert result.status == ResultStatus.SUCCESS
        assert result.confidence.score > 0

    @pytest.mark.asyncio
    async def test_execute_fill(self):
        agent = DesktopAgent(surface=MockSurface())
        goal = AgentGoal(capability="fill", params={"target": "#input", "value": "hello"})
        result = await agent.execute(goal, _make_context())
        assert result.status == ResultStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_type_text(self):
        agent = DesktopAgent(surface=MockSurface())
        goal = AgentGoal(capability="type_text", params={"target": "input", "text": "world"})
        result = await agent.execute(goal, _make_context())
        assert result.status == ResultStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_key_press(self):
        agent = DesktopAgent(surface=MockSurface())
        goal = AgentGoal(capability="key_press", params={"key": "Enter"})
        result = await agent.execute(goal, _make_context())
        assert result.status == ResultStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_scroll(self):
        agent = DesktopAgent(surface=MockSurface())
        goal = AgentGoal(capability="scroll", params={"direction": "down", "amount": 300})
        result = await agent.execute(goal, _make_context())
        assert result.status == ResultStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_screenshot(self):
        agent = DesktopAgent(surface=MockSurface())
        goal = AgentGoal(capability="screenshot", params={})
        result = await agent.execute(goal, _make_context())
        assert result.status == ResultStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_snapshot(self):
        agent = DesktopAgent(surface=MockSurface())
        goal = AgentGoal(capability="snapshot", params={})
        result = await agent.execute(goal, _make_context())
        assert result.status == ResultStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_unknown_capability(self):
        agent = DesktopAgent(surface=MockSurface())
        goal = AgentGoal(capability="fly_to_moon", params={})
        result = await agent.execute(goal, _make_context())
        assert result.status == ResultStatus.FAILURE

    @pytest.mark.asyncio
    async def test_execute_no_surface(self):
        agent = DesktopAgent(surface=None)
        goal = AgentGoal(capability="click", params={"target": "btn"})
        result = await agent.execute(goal, _make_context())
        assert result.status == ResultStatus.CONFIG_ERROR

    @pytest.mark.asyncio
    async def test_dry_run(self):
        agent = DesktopAgent(surface=MockSurface())
        ctx = _make_context(dry_run=True)
        goal = AgentGoal(capability="click", params={"target": "btn"})
        result = await agent.execute(goal, ctx)
        assert result.status == ResultStatus.DRY_RUN
        assert result.metadata["dry_run"] is True


class TestEstimateLifecycle:
    """Estimate should work for all capabilities."""

    @pytest.mark.asyncio
    async def test_estimate_click(self):
        agent = DesktopAgent(surface=MockSurface())
        goal = AgentGoal(capability="click", params={"target": "btn"})
        est = await agent.estimate(goal, _make_context())
        assert est.can_execute is True
        assert est.confidence.score > 0

    @pytest.mark.asyncio
    async def test_estimate_automate(self):
        agent = DesktopAgent(surface=MockSurface())
        goal = AgentGoal(capability="automate", params={"instruction": "test"})
        est = await agent.estimate(goal, _make_context())
        assert est.can_execute is True
        assert est.latency_ms > 1000  # automate is expensive

    @pytest.mark.asyncio
    async def test_estimate_unknown(self):
        agent = DesktopAgent(surface=MockSurface())
        goal = AgentGoal(capability="teleport", params={})
        est = await agent.estimate(goal, _make_context())
        assert est.can_execute is False

    @pytest.mark.asyncio
    async def test_estimate_no_surface(self):
        agent = DesktopAgent(surface=None)
        goal = AgentGoal(capability="click", params={"target": "btn"})
        est = await agent.estimate(goal, _make_context())
        assert est.can_execute is False


class TestUndoLifecycle:
    """Undo + compensate paths."""

    @pytest.mark.asyncio
    async def test_undo_irreversible(self):
        """Undo with no registered compensation → failure."""
        agent = DesktopAgent(surface=MockSurface())
        snap = _snapshot(restore_method=RestoreMethod.NONE)
        result = await agent.undo("exec-1", snap)
        assert result.success is False
        # When no action is registered, undo reports "no undo information"
        assert "no undo" in result.summary.lower() or "irreversible" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_undo_with_state(self):
        """Undo after executing an action → compensation registered → can undo."""
        agent = DesktopAgent(surface=MockSurface())
        ctx = _make_context()
        # Execute a fill action (which registers compensation)
        goal = AgentGoal(capability="fill", params={"target": "#input", "value": "hello"})
        result = await agent.execute(goal, ctx)
        assert result.status == ResultStatus.SUCCESS
        # Now undo using the same execution_id
        snap = _snapshot(
            execution_id=ctx.execution_id,
            restore_method=RestoreMethod.RESTORE_STATE,
            before_state={"value": "old"},
            after_state={"operation": "fill", "target": "#input"},
        )
        undo_result = await agent.undo(ctx.execution_id, snap)
        assert undo_result.success is True

    @pytest.mark.asyncio
    async def test_compensate(self):
        agent = DesktopAgent(surface=MockSurface())
        snap = _snapshot(after_state={"operation": "click"})
        result = await agent.compensate("exec-3", snap)
        assert result.success is False  # Desktop external actions can't auto-compensate
        assert result.manual_instructions is not None


class TestHealthSmoke:
    """Health check smoke test."""

    @pytest.mark.asyncio
    async def test_health_checks_populated(self):
        """Health returns 13 checks (some may fail without full config)."""
        agent = DesktopAgent(surface=MockSurface())
        health = await agent.health()
        assert len(health.checks) == 14  # 9 original + 4 service + 1 macos_adapter (BATCH-33) (BATCH-26)
        assert health.checks["surface"] is True
        assert health.checks["circuit_breaker"] is True
        assert health.checks["cost_budget"] is True
        assert health.checks["key_blocklist"] is True
        assert health.checks["sensitive_apps"] is True
        assert health.checks["menu_service"] is not False
        assert health.checks["taskbar_service"] is not False
        assert health.checks["dialog_service"] is not False
        assert health.checks["desktop_service"] is not False

    @pytest.mark.asyncio
    async def test_surface_na_when_not_configured(self):
        """Surface not configured should return N/A, not unhealthy."""
        agent = DesktopAgent(surface=None)
        health = await agent.health()
        assert health.checks["surface"] is None  # N/A — optional
        assert health.healthy is True  # N/A doesn't break health


class TestSchemaSmoke:
    """Machine-readable schema."""

    def test_schema_returns_valid_dict(self):
        agent = DesktopAgent(surface=MockSurface())
        schema = agent.schema()
        assert schema["schema_version"] == 1
        assert len(schema["capabilities"]) > 0
        assert "status" in schema
        assert "circuit_breaker" in schema["status"]


class TestOrchestrateSmoke:
    """Orchestration smoke with template match."""

    @pytest.mark.asyncio
    async def test_orchestrate_email_to_task(self):
        agent = DesktopAgent(surface=MockSurface())
        goal = AgentGoal(
            capability="orchestrate",
            params={"instruction": "Read email and create a task"},
        )
        result = await agent.execute(goal, _make_context())
        assert result.status == ResultStatus.SUCCESS
        assert result.metadata["decomposition_source"] == "template"

    @pytest.mark.asyncio
    async def test_orchestrate_no_instruction(self):
        agent = DesktopAgent(surface=MockSurface())
        goal = AgentGoal(capability="orchestrate", params={})
        result = await agent.execute(goal, _make_context())
        assert result.status == ResultStatus.FAILURE


class TestSafetySmoke:
    """Rate governor + cost tracker + latency budget wired correctly."""

    @pytest.mark.asyncio
    async def test_rate_governor_accessible(self):
        agent = DesktopAgent(surface=MockSurface())
        gov = agent.rate_governor
        assert gov is not None
        assert gov.check("click") is True

    @pytest.mark.asyncio
    async def test_latency_budget_accessible(self):
        agent = DesktopAgent(surface=MockSurface())
        lb = agent.latency_budget
        assert lb is not None
        m = lb.record("click", 50.0)
        assert m.exceeded is False

    @pytest.mark.asyncio
    async def test_cost_tracker_accessible(self):
        agent = DesktopAgent(surface=MockSurface())
        ct = agent.cost_tracker
        assert ct is not None
        assert ct.budget_exceeded is False
