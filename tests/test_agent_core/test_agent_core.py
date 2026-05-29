"""Tests for deskaoy package — verify it's self-contained and functional."""

import asyncio
import io
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

# =============================================================================
# Import verification — deskaoy has zero browser deps
# =============================================================================

class TestSelfContained:
    """Verify deskaoy imports cleanly without deskaoy."""

    def test_imports_deskaoy(self):
        import deskaoy
        # Verify __version__ is valid semver
        parts = deskaoy.__version__.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_imports_cascade_types(self):
        from deskaoy.cascade.types import Tier, AXNode, AXSnapshot
        assert Tier.SELECTOR == 1
        assert Tier.VISION == 3

    def test_imports_cascade_protocol(self):
        from deskaoy.cascade.protocol import SurfaceAdapter
        assert hasattr(SurfaceAdapter, "click")

    def test_imports_results(self):
        from deskaoy.results import ActionResult, ActionError, action_result
        r = action_result(ok=True, data={"test": 1})
        assert r.ok

    def test_imports_budget_types(self):
        from deskaoy.budget.types import BudgetScope, BudgetConfig
        assert BudgetScope.DAILY == "daily"

    def test_imports_recovery(self):
        from deskaoy.recovery.types import ErrorType, RecoveryStrategy
        from deskaoy.recovery.coordinator import RecoveryCoordinator
        assert ErrorType.TIMEOUT == "timeout"

    def test_imports_verification(self):
        from deskaoy.verification.types import VerificationLevel, PerceptualHash
        from deskaoy.verification.protocol import VerifierAdapter
        assert VerificationLevel.HASH == "hash"

    def test_imports_vision(self):
        from deskaoy.vision.types import VisionTaskComplexity, CascadeConfig
        from deskaoy.vision.providers import AnthropicCUAProvider
        assert VisionTaskComplexity.SIMPLE == "simple"

    def test_imports_tracing(self):
        from deskaoy.tracing.flow_logger import FlowLogger
        from deskaoy.tracing.types import SpanKind
        assert SpanKind.ACTION == "action"

    def test_imports_skills(self):
        from deskaoy.skills.registry import SkillRegistry
        from deskaoy.skills.activation import compute_activation
        assert callable(compute_activation)

    def test_imports_agent_loop(self):
        from deskaoy.agent.loop import AgentLoop
        from deskaoy.agent.loop_detector import ActionLoopDetector
        from deskaoy.agent.registry import ToolRegistry

class TestSurfaceAdapterProtocol:
    """Verify SurfaceAdapter can be implemented and used."""

    def test_concrete_implementation(self):
        from deskaoy.cascade.protocol import SurfaceAdapter
        from deskaoy.results.types import ActionResult, action_result

        class TestSurface(SurfaceAdapter):
            async def click(self, target, **kw): return action_result(ok=True)
            async def fill(self, target, value, **kw): return action_result(ok=True)
            async def screenshot(self): return b""
            async def snapshot(self): return MagicMock()
            async def evaluate(self, expression): return None
            async def key_press(self, key, modifiers=0): return action_result(ok=True)
            async def scroll(self, direction, amount=500): return action_result(ok=True)
            async def type_text(self, text, delay_ms=0): return action_result(ok=True)
            def current_url(self): return "test://"
            async def current_title(self): return "Test"

        surface = TestSurface()
        result = asyncio.run(surface.click("button"))
        assert result.ok

    def test_cannot_instantiate_abc(self):
        from deskaoy.cascade.protocol import SurfaceAdapter
        with pytest.raises(TypeError):
            SurfaceAdapter()


# =============================================================================
# VerifierAdapter protocol — verify it works
# =============================================================================

class TestVerifierAdapterProtocol:

    def test_concrete_implementation(self):
        from deskaoy.verification.protocol import VerifierAdapter

        class TestVerifier(VerifierAdapter):
            async def capture_screenshot(self): return (b"\x89PNG", "abc123")
            async def capture_structural(self, url, title): return MagicMock()
            async def execute_js(self, expression): return None

        adapter = TestVerifier()
        result = asyncio.run(adapter.capture_screenshot())
        assert result[1] == "abc123"


# =============================================================================
# Functional tests — verify core subsystems work standalone
# =============================================================================

class TestCoreFunctionality:

    def test_result_envelope_round_trip(self):
        from deskaoy.results.types import ActionResult, ActionError, ErrorCategory
        err = ActionError(category=ErrorCategory.TIMEOUT, message="timed out")
        r = ActionResult(ok=False, error=err, data=None)
        d = r.to_dict()
        assert d["ok"] is False
        r2 = ActionResult.from_dict(d)
        assert r2.ok is False
        assert r2.error.category == ErrorCategory.TIMEOUT

    def test_perceptual_hash(self):
        from deskaoy.verification.types import PerceptualHash
        h1 = PerceptualHash(dhash=0xABCD, phash=0x1234)
        h2 = PerceptualHash(dhash=0xABCD, phash=0x1234)
        assert h1.hamming_distance(h2) == 0

    def test_compute_hash(self):
        from deskaoy.verification.hasher import compute_hash
        img = Image.new("RGB", (100, 100), "red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        phash = compute_hash(buf.getvalue())
        assert phash.dhash_hex is not None

    def test_budget_governor(self):
        from deskaoy.budget.governor import TokenBudgetGovernor
        from deskaoy.budget.types import BudgetConfig, BudgetScope
        gov = TokenBudgetGovernor(config=BudgetConfig(daily_cap_usd=1.0))
        # check_budget returns None when under budget (no block)
        result = gov.check_budget(BudgetScope.DAILY, estimated_cost_usd=0.01)
        assert result is None  # None = not blocked

    def test_tool_registry(self):
        from deskaoy.agent.registry import ToolRegistry
        reg = ToolRegistry()
        @reg.register
        def test_action():
            return "ok"
        tool = reg.get("test_action")
        assert tool is not None
        assert tool.name == "test_action"

    def test_loop_detector(self):
        from deskaoy.agent.loop_detector import ActionLoopDetector
        det = ActionLoopDetector(window_size=5)
        action = {"action": "click", "target": "#btn1"}
        # No detection for first few reps
        for _ in range(4):
            assert det.record_and_check(action) is None
        # Should detect loop on 5th repetition
        nudge = det.record_and_check(action)
        assert nudge is not None
        assert nudge.level >= 1

    def test_recovery_event_bus(self):
        from deskaoy.recovery.event_bus import WatchdogEventBus
        from deskaoy.recovery.types import WatchdogEvent, WatchdogEventData
        bus = WatchdogEventBus()
        events = []
        bus.subscribe([WatchdogEvent.CRASH_DETECTED], lambda e: events.append(e))
        asyncio.run(bus.emit(WatchdogEventData(
            event_type=WatchdogEvent.CRASH_DETECTED,
            source="test",
            detail="crash",
        )))
        assert len(events) == 1

    def test_skill_activation(self):
        from deskaoy.skills.activation import compute_activation
        from deskaoy.skills.types import DomainSkill
        skill = DomainSkill(
            skill_id="s1", domain="test", name="test_skill",
            description="A test skill", access_count=5,
        )
        score = compute_activation(skill)
        assert score > 0

    def test_checkpoint_round_trip(self, tmp_path):
        from pathlib import Path
        from deskaoy.recovery.checkpoint import CheckpointManager
        mgr = CheckpointManager(workspace=Path(str(tmp_path)))
        asyncio.run(mgr.initialize())
        cp = asyncio.run(mgr.create_checkpoint("test checkpoint"))
        assert cp.message == "test checkpoint"
        loaded = mgr.load_checkpoint_data(cp.checkpoint_id)
        assert loaded is not None
        assert loaded["message"] == "test checkpoint"
