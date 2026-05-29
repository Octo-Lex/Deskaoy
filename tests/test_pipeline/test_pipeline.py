"""Tests for deskaoy.pipeline — G4 Deterministic Pipelines."""

from __future__ import annotations

import asyncio
import pytest

from deskaoy.cascade.protocol import SurfaceAdapter
from deskaoy.results.types import ActionResult, action_result
from deskaoy.pipeline.executor import PipelineExecutor, _resolve_templates, PipelineState
from deskaoy.pipeline.registry import PipelineRegistry
from deskaoy.pipeline.types import PipelineArg, PipelineDefinition, PipelineStep


# ---------------------------------------------------------------------------
# Mock adapter
# ---------------------------------------------------------------------------

class MockSurface(SurfaceAdapter):
    """Minimal mock that records calls."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self._fail_on: set[str] = set()

    def fail_on(self, *actions: str) -> None:
        self._fail_on.update(actions)

    async def click(self, target, **kw):
        self.calls.append(("click", {"target": target, **kw}))
        if "click" in self._fail_on:
            return action_result(ok=False, data={"error": "click failed"})
        return action_result(ok=True)

    async def fill(self, target, value, **kw):
        self.calls.append(("fill", {"target": target, "value": value}))
        return action_result(ok=True)

    async def type_text(self, text):
        self.calls.append(("type_text", {"text": text}))
        if "type_text" in self._fail_on:
            return action_result(ok=False, data={"error": "type failed"})
        return action_result(ok=True)

    async def key_press(self, key, modifiers=0, **kw):
        self.calls.append(("key_press", {"key": key}))
        return action_result(ok=True)

    async def scroll(self, direction="down", amount=3, **kw):
        self.calls.append(("scroll", {"direction": direction}))
        return action_result(ok=True)

    async def hover(self, target, **kw):
        self.calls.append(("hover", {"target": target}))
        return action_result(ok=True)

    async def screenshot(self):
        return b"\x89PNG"

    async def snapshot(self):
        from deskaoy.cascade.types import AXSnapshot
        return AXSnapshot(url="mock://app", title="Mock", nodes={})

    async def evaluate(self, expression):
        return None

    async def select_option(self, target, value, **kw):
        return action_result(ok=False, data={"error": "not supported"})

    async def navigate(self, url, **kw):
        return action_result(ok=False, data={"error": "not supported"})

    async def wait_for_selector(self, target, **kw):
        return action_result(ok=True)

    async def abort(self):
        pass

    async def current_url(self):
        return "mock://app"

    async def current_title(self):
        return "Mock"

    @property
    def supports_navigation(self):
        return False

    @property
    def supports_select(self):
        return False


# ---------------------------------------------------------------------------
# Template resolution
# ---------------------------------------------------------------------------

class TestTemplates:

    def test_resolve_args(self):
        params = {"text": "${args.message}"}
        args = {"message": "Hello World"}
        resolved = _resolve_templates(params, args, PipelineState())
        assert resolved["text"] == "Hello World"

    def test_resolve_no_templates(self):
        params = {"target": "Submit"}
        resolved = _resolve_templates(params, {}, PipelineState())
        assert resolved["target"] == "Submit"

    def test_resolve_mixed(self):
        params = {"target": "Text Editor", "text": "${args.text}"}
        args = {"text": "hello"}
        resolved = _resolve_templates(params, args, PipelineState())
        assert resolved["target"] == "Text Editor"
        assert resolved["text"] == "hello"


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

class TestExecutor:

    @pytest.mark.asyncio
    async def test_simple_pipeline(self):
        pipeline = PipelineDefinition(
            name="test_click", description="Test click",
            steps=[
                PipelineStep("click", {"target": "Submit"}),
            ],
        )
        surface = MockSurface()
        executor = PipelineExecutor()
        result = await executor.execute(pipeline, surface, {})
        assert result.ok
        assert surface.calls == [("click", {"target": "Submit"})]

    @pytest.mark.asyncio
    async def test_pipeline_with_args(self):
        pipeline = PipelineDefinition(
            name="test_type", description="Test type",
            steps=[
                PipelineStep("click", {"target": "Editor"}),
                PipelineStep("type_text", {"text": "${args.text}"}),
            ],
        )
        surface = MockSurface()
        executor = PipelineExecutor()
        result = await executor.execute(pipeline, surface, {"text": "Hello"})
        assert result.ok
        assert surface.calls[1] == ("type_text", {"text": "Hello"})

    @pytest.mark.asyncio
    async def test_pipeline_fails_on_step_error(self):
        pipeline = PipelineDefinition(
            name="test_fail", description="Test fail",
            steps=[
                PipelineStep("click", {"target": "Submit"}),
                PipelineStep("type_text", {"text": "hello"}),
            ],
        )
        surface = MockSurface()
        surface.fail_on("click")
        executor = PipelineExecutor()
        result = await executor.execute(pipeline, surface, {})
        assert not result.ok

    @pytest.mark.asyncio
    async def test_pipeline_with_retry(self):
        pipeline = PipelineDefinition(
            name="test_retry", description="Test retry",
            steps=[
                PipelineStep("type_text", {"text": "hello"}, retry=2),
            ],
        )
        surface = MockSurface()
        surface.fail_on("type_text")
        executor = PipelineExecutor()
        result = await executor.execute(pipeline, surface, {})
        # All retries fail
        assert not result.ok

    @pytest.mark.asyncio
    async def test_pipeline_with_condition_skip(self):
        pipeline = PipelineDefinition(
            name="test_cond", description="Test condition",
            steps=[
                PipelineStep("click", {"target": "A"}),
                PipelineStep("click", {"target": "B"}, condition="snapshot.contains('X')"),
            ],
        )
        surface = MockSurface()
        executor = PipelineExecutor()
        result = await executor.execute(pipeline, surface, {})
        assert result.ok
        # Second step should be skipped (condition not met)
        assert len(surface.calls) == 1

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        pipeline = PipelineDefinition(
            name="test_unknown", description="Test unknown",
            steps=[
                PipelineStep("nonexistent_action", {}),
            ],
        )
        surface = MockSurface()
        executor = PipelineExecutor()
        result = await executor.execute(pipeline, surface, {})
        assert not result.ok


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistry:

    def test_register_and_get(self):
        reg = PipelineRegistry()
        p = PipelineDefinition(name="my_pipe", description="Test")
        reg.register(p)
        assert reg.get("my_pipe") is p

    def test_match_by_name(self):
        reg = PipelineRegistry()
        reg.register(PipelineDefinition(name="notepad_type", description="Type in Notepad"))
        match = reg.match("type hello world in notepad")
        assert match is not None
        assert match.name == "notepad_type"

    def test_no_match(self):
        reg = PipelineRegistry()
        reg.register(PipelineDefinition(name="notepad_type", description="Type in Notepad"))
        match = reg.match("open firefox and browse the web")
        assert match is None

    def test_surface_type_filter(self):
        reg = PipelineRegistry()
        reg.register(PipelineDefinition(name="test", description="Test", surface_type="windows"))
        # Matching instruction but wrong surface type
        assert reg.match("run test on mac", surface_type="macos") is None

    def test_count(self):
        reg = PipelineRegistry()
        reg.register(PipelineDefinition(name="a", description="A"))
        reg.register(PipelineDefinition(name="b", description="B"))
        assert reg.count == 2
