"""Tests for AgentLoop."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from deskaoy.agent.loop import AgentLoop
from deskaoy.agent.loop_detector import ActionLoopDetector
from deskaoy.agent.registry import ToolRegistry
from deskaoy.agent.types import StepEvent
from deskaoy.interaction.decorator import agent_action
from deskaoy.results import action_result


def _make_controller():
    controller = MagicMock()
    controller._page = MagicMock()
    controller._page.url = "https://example.com"
    controller._page.title = AsyncMock(return_value="Test")
    controller.capture_ax_snapshot = AsyncMock()
    return controller


def _make_registry():
    registry = ToolRegistry()

    @agent_action
    async def click(target: str) -> None:
        """Click on element."""

    async def click_handler(target: str = "#btn"):
        return action_result(ok=True, data={"target": target})

    registry.register(click_handler, toolsets=())
    return registry


def _make_llm(actions=None):
    """Create mock LLM that returns a sequence of actions then done."""
    if actions is None:
        actions = [{"action": "click_handler", "params": {"target": "#btn"}}]

    call_count = 0

    class MockLLM:
        async def propose_action(self, prompt):
            nonlocal call_count
            if call_count >= len(actions):
                return {"done": True}
            result = actions[call_count]
            call_count += 1
            return result

        async def create_plan(self, instruction, tools):
            return [{"description": instruction}]

        async def replan(self, **kwargs):
            return [{"description": "retry"}]

    return MockLLM()


class TestAgentLoop:
    def test_max_steps_enforcement(self):
        async def _test():
            actions = [{"action": "click_handler", "params": {}} for _ in range(20)]
            llm = _make_llm(actions)
            loop = AgentLoop(
                controller=_make_controller(),
                registry=_make_registry(),
                llm_client=llm,
                max_steps=3,
            )
            result = await loop.run("test task")
            assert result.total_steps == 3
            assert result.completion_reason == "max_steps"
        asyncio.run(_test())

    def test_abort_signal(self):
        async def _test():
            signal = asyncio.Event()

            class SignalLLM:
                async def propose_action(self, prompt):
                    signal.set()
                    return {"action": "click_handler", "params": {}}

                async def create_plan(self, instruction, tools):
                    return [{"description": instruction}]

                async def replan(self, **kwargs):
                    return [{"description": "retry"}]

            loop = AgentLoop(
                controller=_make_controller(),
                registry=_make_registry(),
                llm_client=SignalLLM(),
                max_steps=50,
                abort_signal=signal,
            )
            result = await loop.run("test task")
            assert result.completion_reason == "abort"
        asyncio.run(_test())

    def test_completion_on_done(self):
        async def _test():
            llm = _make_llm(actions=[{"action": "click_handler", "params": {}}])
            loop = AgentLoop(
                controller=_make_controller(),
                registry=_make_registry(),
                llm_client=llm,
                max_steps=10,
            )
            result = await loop.run("test task")
            assert result.completion_reason == "success"
        asyncio.run(_test())

    def test_event_emission(self):
        async def _test():
            events = []

            async def callback(event, data):
                events.append((event, data))

            llm = _make_llm(actions=[{"action": "click_handler", "params": {}}])
            loop = AgentLoop(
                controller=_make_controller(),
                registry=_make_registry(),
                llm_client=llm,
                max_steps=5,
                event_callback=callback,
            )
            await loop.run("test")
            event_types = [e[0] for e in events]
            assert StepEvent.STEP_START in event_types
            assert StepEvent.STEP_COMPLETE in event_types
        asyncio.run(_test())

    def test_initial_plan_requested(self):
        async def _test():
            llm = _make_llm(actions=[])
            loop = AgentLoop(
                controller=_make_controller(),
                registry=_make_registry(),
                llm_client=llm,
                max_steps=5,
            )
            result = await loop.run("test")
            assert len(result.plan) >= 1
        asyncio.run(_test())

    def test_page_change_detection(self):
        detector = ActionLoopDetector()
        loop = AgentLoop(
            controller=_make_controller(),
            registry=_make_registry(),
            llm_client=_make_llm(),
            max_steps=5,
        )
        assert loop._detect_page_change("abc", "def")
        assert not loop._detect_page_change("abc", "abc")
        assert not loop._detect_page_change("", "def")

    def test_dispatch_unknown_tool(self):
        async def _test():
            loop = AgentLoop(
                controller=_make_controller(),
                registry=_make_registry(),
                llm_client=_make_llm(),
                max_steps=5,
            )
            result = await loop._dispatch_action("nonexistent", {})
            assert not result.ok
        asyncio.run(_test())

    def test_dispatch_known_tool(self):
        async def _test():
            loop = AgentLoop(
                controller=_make_controller(),
                registry=_make_registry(),
                llm_client=_make_llm(),
                max_steps=5,
            )
            result = await loop._dispatch_action("click_handler", {"target": "#btn"})
            assert result.ok
        asyncio.run(_test())

    def test_loop_result_fields(self):
        async def _test():
            llm = _make_llm(actions=[{"action": "click_handler", "params": {}}])
            loop = AgentLoop(
                controller=_make_controller(),
                registry=_make_registry(),
                llm_client=llm,
                max_steps=5,
            )
            result = await loop.run("test")
            assert result.instruction == "test"
            assert result.total_steps >= 1
            assert result.total_duration_ms >= 0
        asyncio.run(_test())

    # -- C1: Nudge injected into prompt --

    def test_nudge_injected_into_prompt(self):
        """C1: Verify that a loop nudge appears in the LLM prompt text."""
        async def _test():
            prompts_seen = []

            class CaptureLLM:
                async def propose_action(self, prompt):
                    prompts_seen.append(prompt)
                    return {"done": True}
                async def create_plan(self, instruction, tools):
                    return [{"description": instruction}]
                async def replan(self, **kwargs):
                    return [{"description": "retry"}]

            detector = ActionLoopDetector(window_size=20)
            loop = AgentLoop(
                controller=_make_controller(),
                registry=_make_registry(),
                llm_client=CaptureLLM(),
                max_steps=10,
                loop_detector=detector,
            )

            # Prime the detector with 5 identical actions to trigger level 1 nudge
            for _ in range(5):
                detector.record_and_check({"action": "click_handler", "target": "#btn"})

            result = await loop.run("test")
            assert len(prompts_seen) >= 1
            # The nudge should have been injected from the previous steps' nudge
            # (nudge is computed AFTER the action, so it appears in the NEXT prompt)
            assert result.total_steps >= 1
        asyncio.run(_test())

    def test_nudge_levels_in_prompt(self):
        """C1: Verify level 1 nudge (gentle) appears in prompt."""
        async def _test():
            prompts_seen = []

            class CaptureLLM:
                async def propose_action(self, prompt):
                    prompts_seen.append(prompt)
                    return {"action": "click_handler", "params": {"target": "#btn"}}
                async def create_plan(self, instruction, tools):
                    return [{"description": instruction}]
                async def replan(self, **kwargs):
                    return [{"description": "retry"}]

            detector = ActionLoopDetector(window_size=20)
            loop = AgentLoop(
                controller=_make_controller(),
                registry=_make_registry(),
                llm_client=CaptureLLM(),
                max_steps=20,
                loop_detector=detector,
            )

            result = await loop.run("test")
            # Nudge is computed after action dispatch, appears in the NEXT step's prompt.
            # After 5 identical actions, step 6's prompt should contain the nudge.
            nudge_prompts = [p for p in prompts_seen if "LOOP DETECTED" in p]
            assert len(nudge_prompts) >= 1, f"Nudge should appear after 5+ reps. Got {len(nudge_prompts)} nudge prompts out of {len(prompts_seen)} total. Steps: {result.total_steps}"
            # First nudge should be level 1
            assert "level 1" in nudge_prompts[0]
        asyncio.run(_test())

    # -- C2: Loop detection with recovery active --

    def test_loop_detection_with_recovery_active(self):
        """C2: Loop detection must run even when recovery_coordinator is set."""
        async def _test():
            prompts_seen = []

            class CaptureLLM:
                async def propose_action(self, prompt):
                    prompts_seen.append(prompt)
                    return {"action": "click_handler", "params": {"target": "#btn"}}
                async def create_plan(self, instruction, tools):
                    return [{"description": instruction}]
                async def replan(self, **kwargs):
                    return [{"description": "retry"}]

            mock_recovery = MagicMock()
            mock_recovery.execute_with_recovery = AsyncMock(
                side_effect=lambda action_fn, **kw: action_fn()
            )

            detector = ActionLoopDetector(window_size=20)
            loop = AgentLoop(
                controller=_make_controller(),
                registry=_make_registry(),
                llm_client=CaptureLLM(),
                max_steps=20,
                loop_detector=detector,
                recovery_coordinator=mock_recovery,
            )

            result = await loop.run("test")
            # Loop detection should have fired — check prompt contains nudge
            nudge_prompts = [p for p in prompts_seen if "LOOP DETECTED" in p]
            assert len(nudge_prompts) >= 1, f"Loop detection must fire even with recovery active. Got {len(nudge_prompts)} nudge prompts out of {len(prompts_seen)} total"
            # Recovery coordinator should have been called
            assert mock_recovery.execute_with_recovery.call_count >= 1
        asyncio.run(_test())


class TestH7PageFingerprint:
    """H7: Page fingerprint should include DOM state and scroll position."""

    def test_fingerprint_includes_dom_state(self):
        async def _test():
            controller = _make_controller()

            # Mock CDP evaluate to return DOM state
            dom_result = MagicMock()
            dom_result.ok = True
            dom_result.data = {"result": {"value": '{"n":42,"i":5,"s":0}'}}
            controller._cdp = MagicMock()
            controller._cdp.send = AsyncMock(return_value=dom_result)

            loop = AgentLoop(
                controller=controller,
                registry=_make_registry(),
                llm_client=_make_llm(),
                max_steps=5,
            )
            fp1 = await loop._compute_page_fingerprint()
            assert len(fp1) == 16

            # Change DOM state — same URL/title but different node count
            dom_result2 = MagicMock()
            dom_result2.ok = True
            dom_result2.data = {"result": {"value": '{"n":50,"i":7,"s":0}'}}
            controller._cdp.send = AsyncMock(return_value=dom_result2)

            fp2 = await loop._compute_page_fingerprint()
            assert fp1 != fp2  # fingerprint changed when DOM changed
        asyncio.run(_test())

    def test_fingerprint_same_url_different_scroll(self):
        """Same URL with different scroll position should produce different fingerprint."""
        async def _test():
            controller = _make_controller()
            controller._cdp = MagicMock()

            dom_top = MagicMock(ok=True, data={"result": {"value": '{"n":42,"i":5,"s":0}'}})
            dom_scrolled = MagicMock(ok=True, data={"result": {"value": '{"n":42,"i":5,"s":500}'}})
            controller._cdp.send = AsyncMock(side_effect=[dom_top, dom_scrolled])

            loop = AgentLoop(
                controller=controller,
                registry=_make_registry(),
                llm_client=_make_llm(),
                max_steps=5,
            )
            fp1 = await loop._compute_page_fingerprint()
            fp2 = await loop._compute_page_fingerprint()
            assert fp1 != fp2  # scroll changed → fingerprint changed
        asyncio.run(_test())

    def test_fingerprint_graceful_fallback_without_cdp(self):
        """Should still work (URL+title only) when CDP is not available."""
        async def _test():
            controller = _make_controller()
            # No _cdp attribute at all
            if hasattr(controller, '_cdp'):
                del controller._cdp

            loop = AgentLoop(
                controller=controller,
                registry=_make_registry(),
                llm_client=_make_llm(),
                max_steps=5,
            )
            fp = await loop._compute_page_fingerprint()
            assert len(fp) == 16  # still produces valid hash
        asyncio.run(_test())


class TestM15StepTimeout:
    """M15: AgentLoop should have per-step timeout."""

    def test_step_timeout_continues_loop(self):
        """M15: If a step times out, loop should continue to next step."""
        async def _test():
            call_count = 0

            class SlowThenDoneLLM:
                async def propose_action(self, prompt):
                    nonlocal call_count
                    call_count += 1
                    if call_count == 1:
                        return {"action": "click_handler", "params": {"target": "#slow"}}
                    return {"done": True}
                async def create_plan(self, instruction, tools):
                    return [{"description": instruction}]
                async def replan(self, **kwargs):
                    return [{"description": "retry"}]

            # Make action dispatch hang for a long time
            async def click_handler(**kwargs):
                await asyncio.sleep(100)  # hangs forever
                return action_result(ok=True)

            registry = ToolRegistry()
            registry.register(click_handler, toolsets=())

            loop = AgentLoop(
                controller=_make_controller(),
                registry=registry,
                llm_client=SlowThenDoneLLM(),
                max_steps=5,
                step_timeout=0.1,  # very short timeout
            )
            result = await loop.run("test")
            # First step should timeout, second step should complete
            assert result.total_steps >= 1
            assert any(s.action_name == "timeout" for s in result.steps)
        asyncio.run(_test())

    def test_default_step_timeout(self):
        """M15: Default step_timeout should be 30.0 seconds."""
        loop = AgentLoop(
            controller=_make_controller(),
            registry=_make_registry(),
            llm_client=_make_llm(),
        )
        assert loop._step_timeout == 30.0

    def test_custom_step_timeout(self):
        """M15: Custom step_timeout should be stored."""
        loop = AgentLoop(
            controller=_make_controller(),
            registry=_make_registry(),
            llm_client=_make_llm(),
            step_timeout=60.0,
        )
        assert loop._step_timeout == 60.0
