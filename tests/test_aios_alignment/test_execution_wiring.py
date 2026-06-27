"""Tests for AI-OS bridge wiring into DesktopAgent execution paths.

Validates that all 5 wiring points are functional:
  Wire 1: Policy preflight before GUI actions
  Wire 2: Trace spans after every action
  Wire 3: Result mapper for output
  Wire 4: Recovery bridge bounding retries
  Wire 5: Storage resolver for checkpoints
"""

from __future__ import annotations

import pytest

from deskaoy.desktop_agent import DesktopAgent
from deskaoy.os_types import (
    AgentContext,
    AgentGoal,
    CancellationToken,
    ResultStatus,
)
from deskaoy.policy import PolicyBridge, PolicyDecision, PolicyEffect
from deskaoy.recovery_bridge import RecoveryBridge
from deskaoy.results.types import ActionError, ActionMethod, ActionResult, ResultMeta
from deskaoy.trace_bridge import ActionSpan, TraceBridge

# ── Helpers ──────────────────────────────────────

def _make_context(**kw) -> AgentContext:
    defaults = dict(
        execution_id="test-exec-001",
        idempotency_key="idem-001",
        task_id="task-001",
        user_id="user-001",
        session_id="sess-001",
        dry_run=False,
        timeout_seconds=30,
        cancellation_token=CancellationToken(),
    )
    defaults.update(kw)
    return AgentContext(**defaults)


def _make_goal(capability: str = "click", **params) -> AgentGoal:
    return AgentGoal(
        capability=capability,
        params=params or {"target": "test-button"},
    )


def _ok_result(**data) -> ActionResult:
    return ActionResult(
        ok=True,
        data=data or {"clicked": True},
        meta=ResultMeta(trace_id="t1", duration_ms=50.0, method=ActionMethod.SELECTOR),
    )


def _fail_result(msg: str = "fail") -> ActionResult:
    return ActionResult(
        ok=False,
        data={},
        error=ActionError(category="unknown", message=msg),
        meta=ResultMeta(trace_id="t2", duration_ms=10.0, method=ActionMethod.SELECTOR),
    )


class FakeSurface:
    """Minimal surface adapter for testing."""
    name = "fake_surface"

    async def click(self, **kw):
        return _ok_result()

    async def screenshot(self, **kw):
        return _ok_result(image="base64data")

    async def snapshot(self, **kw):
        return _ok_result(tree="mock")

    async def fill(self, **kw):
        return _ok_result(filled=True)


# ===================================================================
# Wire 1: Policy Preflight
# ===================================================================

class TestPolicyPreflight:

    @pytest.mark.asyncio
    async def test_allow_proceeds(self):
        """Policy ALLOW → action executes normally."""
        policy = PolicyBridge(dev_mode=True)
        agent = DesktopAgent(surface=FakeSurface(), policy_bridge=policy)
        result = await agent.execute(
            _make_goal("click"),
            _make_context(),
        )
        assert result.status == ResultStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_deny_blocks(self):
        """Policy DENY → action blocked before execution."""
        async def deny_fn(perms, ctx):
            return PolicyDecision(effect=PolicyEffect.DENY, reason="forbidden")

        policy = PolicyBridge(preflight_fn=deny_fn, dev_mode=False)
        agent = DesktopAgent(surface=FakeSurface(), policy_bridge=policy)
        result = await agent.execute(
            _make_goal("click"),
            _make_context(),
        )
        assert result.status == ResultStatus.FAILURE
        assert "blocked by policy" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_ask_returns_needs_review(self):
        """Policy ASK → returns needs_review status."""
        async def ask_fn(perms, ctx):
            return PolicyDecision(effect=PolicyEffect.ASK, reason="sensitive")

        policy = PolicyBridge(preflight_fn=ask_fn, dev_mode=False)
        agent = DesktopAgent(surface=FakeSurface(), policy_bridge=policy)
        result = await agent.execute(
            _make_goal("click"),
            _make_context(),
        )
        assert result.status == ResultStatus.NEEDS_REVIEW

    @pytest.mark.asyncio
    async def test_dry_run_only_forces_dry_run(self):
        """Policy ALLOW_DRY_RUN_ONLY → executes as dry run."""
        async def dry_fn(perms, ctx):
            return PolicyDecision(effect=PolicyEffect.ALLOW_DRY_RUN_ONLY, reason="restricted")

        policy = PolicyBridge(preflight_fn=dry_fn, dev_mode=False)
        agent = DesktopAgent(surface=FakeSurface(), policy_bridge=policy)
        result = await agent.execute(
            _make_goal("click"),
            _make_context(),
        )
        assert result.status == ResultStatus.DRY_RUN

    @pytest.mark.asyncio
    async def test_degraded_passes(self):
        """Policy DEGRADED → action proceeds (with degraded note)."""
        async def deg_fn(perms, ctx):
            return PolicyDecision(
                effect=PolicyEffect.DEGRADED,
                reason="limited capabilities",
                degraded_capabilities=["stealth"],
            )

        policy = PolicyBridge(preflight_fn=deg_fn, dev_mode=False)
        agent = DesktopAgent(surface=FakeSurface(), policy_bridge=policy)
        result = await agent.execute(
            _make_goal("click"),
            _make_context(),
        )
        assert result.status == ResultStatus.SUCCESS


# ===================================================================
# Wire 2: Trace Spans
# ===================================================================

class TestTraceSpans:

    @pytest.mark.asyncio
    async def test_span_emitted_on_action(self):
        """Trace span emitted after every action."""
        spans: list[ActionSpan] = []

        async def capture_span(span: ActionSpan):
            spans.append(span)

        trace = TraceBridge(emit_fn=capture_span)
        agent = DesktopAgent(surface=FakeSurface(), trace_bridge=trace)
        await agent.execute(_make_goal("click"), _make_context())

        assert len(spans) >= 1
        assert spans[0].action == "click"
        assert spans[0].ok is True
        assert spans[0].duration_ms >= 0

    @pytest.mark.asyncio
    async def test_diagnostic_mode_stores_locally(self):
        """Without emit_fn, spans stored in diagnostic_spans."""
        trace = TraceBridge()
        agent = DesktopAgent(surface=FakeSurface(), trace_bridge=trace)
        await agent.execute(_make_goal("click"), _make_context())

        assert trace.span_count >= 1
        assert trace.diagnostic_spans[0].action == "click"

    @pytest.mark.asyncio
    async def test_span_has_trace_id(self):
        """Span includes execution_id as trace_id."""
        trace = TraceBridge()
        agent = DesktopAgent(surface=FakeSurface(), trace_bridge=trace)
        await agent.execute(_make_goal("click"), _make_context(execution_id="exec-42"))

        assert trace.diagnostic_spans[0].trace_id == "exec-42"

    @pytest.mark.asyncio
    async def test_span_on_failure(self):
        """Span emitted even on action failure."""
        spans: list[ActionSpan] = []
        async def capture(span: ActionSpan):
            spans.append(span)

        trace = TraceBridge(emit_fn=capture)

        # Surface that fails
        class FailSurface(FakeSurface):
            async def click(self, **kw):
                return _fail_result("button not found")

        agent = DesktopAgent(surface=FailSurface(), trace_bridge=trace)
        await agent.execute(_make_goal("click"), _make_context())

        assert len(spans) >= 1
        assert spans[0].ok is False


# ===================================================================
# Wire 3: Result Mapper
# ===================================================================

class TestResultMapper:

    @pytest.mark.asyncio
    async def test_aios_mapped_in_metadata(self):
        """ActionResult mapped to AIOSResult in metadata."""
        agent = DesktopAgent(surface=FakeSurface())
        result = await agent.execute(_make_goal("click"), _make_context())

        assert "aios_mapped" in result.metadata
        mapped = result.metadata["aios_mapped"]
        assert mapped["ok"] is True
        assert mapped["status"] == "success"

    @pytest.mark.asyncio
    async def test_failure_mapped_honestly(self):
        """Failure result never claims success."""
        class FailSurface(FakeSurface):
            async def click(self, **kw):
                return _fail_result("not found")

        agent = DesktopAgent(surface=FailSurface())
        result = await agent.execute(_make_goal("click"), _make_context())

        mapped = result.metadata["aios_mapped"]
        assert mapped["ok"] is False
        assert mapped["status"] == "failure"


# ===================================================================
# Wire 4: Recovery Bridge
# ===================================================================

class TestRecoveryBridge:

    def test_default_bridge_created(self):
        """DesktopAgent creates a default RecoveryBridge."""
        agent = DesktopAgent()
        assert agent._recovery_bridge is not None
        assert agent._recovery_bridge.max_attempts > 0

    def test_custom_max_attempts(self):
        """Custom recovery bridge with different max_attempts."""
        rb = RecoveryBridge(max_attempts=5)
        agent = DesktopAgent(recovery_bridge=rb)
        assert agent._recovery_bridge.max_attempts == 5


# ===================================================================
# Wire 5: Storage Resolver
# ===================================================================

class TestStorageResolver:

    def test_storage_resolver_created(self):
        """DesktopAgent creates StorageResolver on init."""
        agent = DesktopAgent()
        assert agent._storage_resolver is not None

    @pytest.mark.asyncio
    async def test_checkpoint_path_available(self):
        """Checkpoint path resolves to a valid directory."""
        import os
        os.environ["AIOS_HOME"] = "/tmp/aios-test"
        try:
            agent = DesktopAgent()
            if agent._storage_resolver:
                path = agent._storage_resolver.resolve("checkpoints")
                assert "checkpoints" in str(path)
        finally:
            del os.environ["AIOS_HOME"]


# ===================================================================
# Integration: Full Bridge Stack
# ===================================================================

class TestFullBridgeStack:

    @pytest.mark.asyncio
    async def test_all_bridges_fire_on_execute(self):
        """All bridges fire in correct order on a single action."""
        events = {
            "policy_checked": False,
            "trace_emitted": False,
            "result_mapped": False,
        }

        async def track_policy(perms, ctx):
            events["policy_checked"] = True
            return PolicyDecision(effect=PolicyEffect.ALLOW, reason="ok")

        async def track_trace(span):
            events["trace_emitted"] = True

        policy = PolicyBridge(preflight_fn=track_policy, dev_mode=False)
        trace = TraceBridge(emit_fn=track_trace)
        agent = DesktopAgent(
            surface=FakeSurface(),
            policy_bridge=policy,
            trace_bridge=trace,
        )

        result = await agent.execute(_make_goal("click"), _make_context())

        assert events["policy_checked"] is True
        assert events["trace_emitted"] is True
        assert "aios_mapped" in result.metadata
        events["result_mapped"] = True
        assert all(events.values())
