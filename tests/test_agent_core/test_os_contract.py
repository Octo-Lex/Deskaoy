"""AI-OS Agent Protocol Contract Test Suite (PLATFORM_CONTRACT v2.2 §7).

These tests verify that DesktopAgent complies with the Agent Protocol.
Every citizen must pass these tests before registration.

All methods are async — use pytest-asyncio.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from deskaoy.desktop_agent import DesktopAgent
from deskaoy.os_types import (
    AgentContext,
    AgentEstimate,
    AgentGoal,
    AgentResult,
    CancellationToken,
    Confidence,
    ErrorCode,
    Issue,
    IssueSeverity,
    RestoreMethod,
    ResultStatus,
    Snapshot,
    UndoResult,
)
from deskaoy.results.types import ActionResult, ResultMeta

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class MockSurface:
    """Mock SurfaceAdapter for testing."""

    def __init__(self):
        self.click_count = 0
        self.last_fill_target = None
        self.last_fill_value = None

    async def click(self, target: str, *, dry_run: bool = False, **kwargs: Any) -> ActionResult:
        self.click_count += 1
        return ActionResult(
            ok=True,
            data={"clicked": target},
            meta=ResultMeta(trace_id="test", duration_ms=10.0),
        )

    async def fill(self, target: str, value: str, *, dry_run: bool = False, **kwargs: Any) -> ActionResult:
        self.last_fill_target = target
        self.last_fill_value = value
        return ActionResult(
            ok=True,
            data={"filled": target, "value": value},
            meta=ResultMeta(trace_id="test", duration_ms=5.0),
        )

    async def type_text(self, text: str, delay_ms: float = 0, *, dry_run: bool = False) -> ActionResult:
        return ActionResult(
            ok=True,
            data={"typed": text},
            meta=ResultMeta(trace_id="test", duration_ms=20.0),
        )

    async def key_press(self, key: str, modifiers: int = 0, *, dry_run: bool = False) -> ActionResult:
        return ActionResult(
            ok=True,
            data={"key": key, "modifiers": modifiers},
            meta=ResultMeta(trace_id="test", duration_ms=2.0),
        )

    async def scroll(self, direction: str, amount: int = 500, *, dry_run: bool = False) -> ActionResult:
        return ActionResult(
            ok=True,
            data={"scrolled": direction, "amount": amount},
            meta=ResultMeta(trace_id="test", duration_ms=15.0),
        )

    async def screenshot(self) -> bytes:
        return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    async def snapshot(self) -> Any:
        from deskaoy.cascade.types import AXSnapshot
        return AXSnapshot(
            nodes=[{"role": "window", "name": "Test"}],
            focus_url="test://window",
            title="Test Window",
        )

    async def evaluate(self, expression: str) -> Any:
        return None

    def current_url(self) -> str:
        return "test://desktop"

    async def current_title(self) -> str:
        return "Test Desktop"


def _mock_context(
    dry_run: bool = False,
    cancelled: bool = False,
    timeout_seconds: int = 60,
    client: Any = None,
) -> AgentContext:
    token = CancellationToken()
    if cancelled:
        token.cancel()
    return AgentContext(
        execution_id="exec-001",
        idempotency_key="idem-001",
        task_id="task-001",
        user_id="user-001",
        session_id="sess-001",
        dry_run=dry_run,
        timeout_seconds=timeout_seconds,
        cancellation_token=token,
        client=client,
    )


def _valid_goal(capability: str = "click", **params) -> AgentGoal:
    return AgentGoal(
        capability=capability,
        params=params or {"target": "#button"},
    )


@pytest.fixture
def surface():
    return MockSurface()


@pytest.fixture
def agent(surface):
    return DesktopAgent(surface=surface)


# ---------------------------------------------------------------------------
# §7 Contract Tests — Identity
# ---------------------------------------------------------------------------

class TestIdentity:
    """Has all required identity fields."""

    @pytest.mark.asyncio
    async def test_name_valid(self, agent):
        assert agent.name and re.match(r'^[a-z][a-z0-9_]*$', agent.name)

    @pytest.mark.asyncio
    async def test_display_name(self, agent):
        assert agent.display_name

    @pytest.mark.asyncio
    async def test_description(self, agent):
        assert agent.description

    @pytest.mark.asyncio
    async def test_version(self, agent):
        assert agent.version

    @pytest.mark.asyncio
    async def test_domains(self, agent):
        assert agent.domains
        assert "desktop_automation" in agent.domains

    @pytest.mark.asyncio
    async def test_capabilities_nonempty(self, agent):
        assert agent.capabilities

    @pytest.mark.asyncio
    async def test_action_classes_cover_capabilities(self, agent):
        """Every capability MUST have an entry in action_classes."""
        for cap in agent.capabilities:
            assert cap in agent.action_classes, f"Missing action_class for {cap}"
            assert agent.action_classes[cap] in {
                "read_only", "recoverable", "draftable",
                "sensitive", "external", "irreversible",
            }


# ---------------------------------------------------------------------------
# §7 Contract Tests — Dry Run
# ---------------------------------------------------------------------------

class TestDryRun:
    """Dry run returns without side effects."""

    @pytest.mark.asyncio
    async def test_dry_run_returns_status(self, agent):
        ctx = _mock_context(dry_run=True)
        goal = _valid_goal("click", target="#button")
        result = await agent.execute(goal, ctx)
        assert result.status == ResultStatus.DRY_RUN
        assert result.summary
        assert result.execution_id == ctx.execution_id

    @pytest.mark.asyncio
    async def test_dry_run_no_mutations(self, agent, surface):
        ctx = _mock_context(dry_run=True)
        goal = _valid_goal("fill", target="#input", value="test")
        result = await agent.execute(goal, ctx)
        assert result.mutations == []
        # Surface should NOT have been called
        assert surface.last_fill_target is None

    @pytest.mark.asyncio
    async def test_dry_run_confidence(self, agent):
        ctx = _mock_context(dry_run=True)
        goal = _valid_goal("click", target="#button")
        result = await agent.execute(goal, ctx)
        assert result.confidence.score == 1.0
        assert "Dry run" in result.confidence.reason


# ---------------------------------------------------------------------------
# §7 Contract Tests — Real Execution
# ---------------------------------------------------------------------------

class TestRealExecution:
    """Real execution returns valid result."""

    @pytest.mark.asyncio
    async def test_execute_returns_agent_result(self, agent):
        ctx = _mock_context()
        goal = _valid_goal("click", target="#button")
        result = await agent.execute(goal, ctx)
        assert isinstance(result, AgentResult)
        assert result.execution_id == ctx.execution_id
        assert result.summary
        assert isinstance(result.status, ResultStatus)

    @pytest.mark.asyncio
    async def test_execute_confidence(self, agent):
        ctx = _mock_context()
        goal = _valid_goal("click", target="#button")
        result = await agent.execute(goal, ctx)
        assert isinstance(result.confidence, Confidence)
        assert 0.0 <= result.confidence.score <= 1.0

    @pytest.mark.asyncio
    async def test_execute_success(self, agent, surface):
        ctx = _mock_context()
        goal = _valid_goal("click", target="#button")
        result = await agent.execute(goal, ctx)
        assert result.status == ResultStatus.SUCCESS
        assert surface.click_count == 1

    @pytest.mark.asyncio
    async def test_execute_fill(self, agent, surface):
        ctx = _mock_context()
        goal = _valid_goal("fill", target="#search", value="hello")
        result = await agent.execute(goal, ctx)
        assert result.status == ResultStatus.SUCCESS
        assert surface.last_fill_target == "#search"
        assert surface.last_fill_value == "hello"


# ---------------------------------------------------------------------------
# §7 Contract Tests — Estimate
# ---------------------------------------------------------------------------

class TestEstimate:
    """estimate() returns valid AgentEstimate."""

    @pytest.mark.asyncio
    async def test_estimate_valid(self, agent):
        ctx = _mock_context()
        goal = _valid_goal()
        est = await agent.estimate(goal, ctx)
        assert isinstance(est, AgentEstimate)
        assert est.can_execute is True
        assert est.cost_usd >= 0
        assert est.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_estimate_unknown_capability(self, agent):
        ctx = _mock_context()
        goal = AgentGoal(capability="nonexistent")
        est = await agent.estimate(goal, ctx)
        assert est.can_execute is False
        assert "Unknown" in est.refusal_reason

    @pytest.mark.asyncio
    async def test_estimate_no_surface(self):
        agent = DesktopAgent()  # No surface
        ctx = _mock_context()
        goal = _valid_goal()
        est = await agent.estimate(goal, ctx)
        assert est.can_execute is False
        assert est.provider_healthy is False

    @pytest.mark.asyncio
    async def test_estimate_confidence_structured(self, agent):
        ctx = _mock_context()
        goal = _valid_goal()
        est = await agent.estimate(goal, ctx)
        assert isinstance(est.confidence, Confidence)
        assert 0.0 <= est.confidence.score <= 1.0


# ---------------------------------------------------------------------------
# §7 Contract Tests — Undo
# ---------------------------------------------------------------------------

class TestUndo:
    """Recoverable/sensitive actions support undo."""

    @pytest.mark.asyncio
    async def test_undo_returns_undo_result(self, agent, surface):
        # First execute a fill (sensitive action)
        ctx = _mock_context()
        goal = _valid_goal("fill", target="#input", value="new_value")
        exec_result = await agent.execute(goal, ctx)
        assert exec_result.status == ResultStatus.SUCCESS

        # Now undo it
        if exec_result.mutations:
            mut = exec_result.mutations[0]
            snapshot = Snapshot(
                snapshot_id="snap-001",
                execution_id=ctx.execution_id,
                resource_type=mut.resource_type,
                resource_id=mut.resource_id,
                before_state=mut.before_state,
                after_state=mut.after_state,
                restore_method=mut.restore_method,
                state_version="",
                created_at="2026-01-01T00:00:00Z",
                expires_at="2026-02-01T00:00:00Z",
            )
            undo_result = await agent.undo(ctx.execution_id, snapshot)
            assert isinstance(undo_result, UndoResult)
            assert undo_result.execution_id == ctx.execution_id

    @pytest.mark.asyncio
    async def test_undo_irreversible(self, agent):
        snapshot = Snapshot(
            snapshot_id="snap-002",
            execution_id="exec-002",
            resource_type="desktop",
            resource_id="test",
            before_state=None,
            after_state=None,
            restore_method=RestoreMethod.NONE,
            state_version="",
            created_at="2026-01-01T00:00:00Z",
            expires_at="2026-02-01T00:00:00Z",
        )
        undo_result = await agent.undo("exec-002", snapshot)
        assert isinstance(undo_result, UndoResult)
        assert undo_result.success is False

    @pytest.mark.asyncio
    async def test_compensate_returns_undo_result(self, agent):
        snapshot = Snapshot(
            snapshot_id="snap-003",
            execution_id="exec-003",
            resource_type="desktop",
            resource_id="test",
            before_state={},
            after_state={"operation": "send"},
            restore_method=RestoreMethod.COMPENSATE,
            state_version="",
            created_at="2026-01-01T00:00:00Z",
            expires_at="2026-02-01T00:00:00Z",
        )
        result = await agent.compensate("exec-003", snapshot)
        assert isinstance(result, UndoResult)


# ---------------------------------------------------------------------------
# §7 Contract Tests — Missing Auth / Dependencies
# ---------------------------------------------------------------------------

class TestMissingDependencies:
    """Gracefully handles missing surface adapter."""

    @pytest.mark.asyncio
    async def test_no_surface_returns_failure(self):
        agent = DesktopAgent()  # No surface
        ctx = _mock_context()
        goal = _valid_goal()
        result = await agent.execute(goal, ctx)
        assert isinstance(result, AgentResult)
        assert result.status == ResultStatus.CONFIG_ERROR
        # Should have DEPENDENCY_MISSING issue
        dep_issues = [i for i in result.issues if i.code == ErrorCode.DEPENDENCY_MISSING]
        assert len(dep_issues) > 0


# ---------------------------------------------------------------------------
# §7 Contract Tests — Timeout
# ---------------------------------------------------------------------------

class TestTimeout:
    """Respects timeout."""

    @pytest.mark.asyncio
    async def test_execute_with_timeout(self, agent):
        ctx = _mock_context(timeout_seconds=30)
        goal = _valid_goal()
        result = await agent.execute(goal, ctx)
        assert isinstance(result, AgentResult)


# ---------------------------------------------------------------------------
# §7 Contract Tests — Cancellation
# ---------------------------------------------------------------------------

class TestCancellation:
    """Handles cancellation gracefully."""

    @pytest.mark.asyncio
    async def test_cancelled_before_execution(self, agent):
        ctx = _mock_context(cancelled=True)
        goal = _valid_goal()
        result = await agent.execute(goal, ctx)
        assert isinstance(result, AgentResult)
        assert result.status == ResultStatus.CANCELLED


# ---------------------------------------------------------------------------
# §7 Contract Tests — Confidence Structure
# ---------------------------------------------------------------------------

class TestConfidenceStructure:
    """Returns structured confidence with score and reason."""

    @pytest.mark.asyncio
    async def test_confidence_always_structured(self, agent):
        ctx = _mock_context()
        goal = _valid_goal()
        result = await agent.execute(goal, ctx)
        assert isinstance(result.confidence, Confidence)
        assert 0.0 <= result.confidence.score <= 1.0

    @pytest.mark.asyncio
    async def test_low_confidence_has_reason(self, agent):
        # Execute with unknown capability → low confidence
        ctx = _mock_context()
        goal = AgentGoal(capability="nonexistent")
        result = await agent.execute(goal, ctx)
        assert result.confidence.score < 0.8
        assert result.confidence.reason

    @pytest.mark.asyncio
    async def test_grounding_confidence_used(self, agent):
        """When visual_confidence is in ActionResult.data, DesktopAgent uses it."""
        ctx = _mock_context()
        goal = _valid_goal()

        # Override click to return grounding confidence
        original_click = agent._surface.click
        async def click_with_grounding(target, **kwargs):
            result = await original_click(target, **kwargs)
            result.data["visual_confidence"] = 0.72
            return result
        agent._surface.click = click_with_grounding

        result = await agent.execute(goal, ctx)
        assert result.confidence.score == pytest.approx(0.72)
        assert result.confidence.factors.get("source") == "grounding_pipeline"

        # Restore
        agent._surface.click = original_click


# ---------------------------------------------------------------------------
# §7 Contract Tests — Issues Structure
# ---------------------------------------------------------------------------

class TestIssuesStructure:
    """All issues are Issue type with severity and code."""

    @pytest.mark.asyncio
    async def test_issues_are_structured(self, agent):
        ctx = _mock_context()
        goal = AgentGoal(capability="nonexistent")
        result = await agent.execute(goal, ctx)
        if result.issues:
            assert all(isinstance(i, Issue) for i in result.issues)
            assert all(isinstance(i.severity, IssueSeverity) for i in result.issues)
            assert all(isinstance(i.code, ErrorCode) for i in result.issues)
            assert all(i.message for i in result.issues)


# ---------------------------------------------------------------------------
# §7 Contract Tests — Metadata
# ---------------------------------------------------------------------------

class TestMetadata:
    """Returns metadata for audit."""

    @pytest.mark.asyncio
    async def test_metadata_present(self, agent):
        ctx = _mock_context()
        goal = _valid_goal()
        result = await agent.execute(goal, ctx)
        assert isinstance(result.metadata, dict)
        assert "duration_ms" in result.metadata
        assert "provider" in result.metadata


# ---------------------------------------------------------------------------
# §7 Contract Tests — Execution ID Echo
# ---------------------------------------------------------------------------

class TestExecutionIdEcho:
    """Every result echoes the execution_id from context."""

    @pytest.mark.asyncio
    async def test_echo_execution_id(self, agent):
        ctx = _mock_context()
        goal = _valid_goal()
        result = await agent.execute(goal, ctx)
        assert result.execution_id == ctx.execution_id

    @pytest.mark.asyncio
    async def test_echo_in_dry_run(self, agent):
        ctx = _mock_context(dry_run=True)
        goal = _valid_goal()
        result = await agent.execute(goal, ctx)
        assert result.execution_id == ctx.execution_id

    @pytest.mark.asyncio
    async def test_echo_in_failure(self, agent):
        agent_no_surf = DesktopAgent()  # No surface
        ctx = _mock_context()
        goal = _valid_goal()
        result = await agent_no_surf.execute(goal, ctx)
        assert result.execution_id == ctx.execution_id


# ---------------------------------------------------------------------------
# §7 Contract Tests — Mutation Records
# ---------------------------------------------------------------------------

class TestMutationRecords:
    """Actions with action_class >= recoverable return mutation records."""

    @pytest.mark.asyncio
    async def test_sensitive_action_has_mutations(self, agent, surface):
        ctx = _mock_context()
        # "fill" is classified as "sensitive"
        goal = _valid_goal("fill", target="#input", value="hello")
        result = await agent.execute(goal, ctx)
        assert result.status == ResultStatus.SUCCESS
        assert len(result.mutations) > 0
        mut = result.mutations[0]
        assert mut.resource_type
        assert mut.operation
        assert isinstance(mut.restore_method, RestoreMethod)

    @pytest.mark.asyncio
    async def test_read_only_no_mutations(self, agent, surface):
        ctx = _mock_context()
        # "scroll" is classified as "read_only"
        goal = _valid_goal("scroll", direction="down", amount=300)
        result = await agent.execute(goal, ctx)
        assert result.status == ResultStatus.SUCCESS
        assert len(result.mutations) == 0


# ---------------------------------------------------------------------------
# §7 Contract Tests — Domain Enforcement
# ---------------------------------------------------------------------------

class TestDomainEnforcement:
    """Agent declares its domain correctly."""

    @pytest.mark.asyncio
    async def test_domain_declared(self, agent):
        assert "desktop_automation" in agent.domains
        # Must not have wildcard or empty domains
        assert "" not in agent.domains
        assert "*" not in agent.domains

    @pytest.mark.asyncio
    async def test_learnings_domain_scoped(self, agent, surface):
        ctx = _mock_context()
        goal = _valid_goal("click", target="#button")
        result = await agent.execute(goal, ctx)
        for learning in result.learnings:
            assert learning.domain in agent.domains
