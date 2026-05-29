"""Tests for step context window (LangExtract pattern C)."""

import pytest
from deskaoy.agent.context import StepContext, build_step_context, _format_action


# ---------------------------------------------------------------------------
# StepContext
# ---------------------------------------------------------------------------

class TestStepContext:
    def test_empty_context(self):
        ctx = StepContext()
        assert ctx.to_prompt_text() == ""
        assert not ctx.has_context

    def test_single_prev_action(self):
        ctx = StepContext(prev_action="click(Submit)", prev_result="ok")
        text = ctx.to_prompt_text()
        assert "Previous action: click(Submit) → ok" in text

    def test_failed_prev_action(self):
        ctx = StepContext(prev_action="click(Submit)", prev_result="failed: not_found")
        text = ctx.to_prompt_text()
        assert "failed: not_found" in text

    def test_recent_actions_limited(self):
        ctx = StepContext(recent_actions=[f"action_{i}" for i in range(10)])
        assert len(ctx.recent_actions) == 10  # stored as-is
        text = ctx.to_prompt_text()
        # Only last 5 appear in prompt text
        assert "action_9" in text
        assert "action_5" in text

    def test_errors_included(self):
        ctx = StepContext(errors_so_far=["step 1: timeout", "step 3: not_found"])
        text = ctx.to_prompt_text()
        assert "Errors so far:" in text
        assert "timeout" in text

    def test_url_and_title(self):
        ctx = StepContext(current_url="file:///doc.txt", current_title="Untitled")
        text = ctx.to_prompt_text()
        assert "Current URL: file:///doc.txt" in text
        assert "Current title: Untitled" in text

    def test_max_context_chars(self):
        ctx = StepContext(
            prev_action="x" * 600,
            max_context_chars=500,
        )
        text = ctx.to_prompt_text()
        assert len(text) <= 500
        assert text.endswith("...")

    def test_has_context(self):
        assert StepContext(prev_action="click").has_context
        assert StepContext(recent_actions=["click"]).has_context
        assert StepContext(errors_so_far=["err"]).has_context
        assert not StepContext().has_context

    def test_to_dict(self):
        ctx = StepContext(
            prev_action="click(btn)",
            prev_result="ok",
            recent_actions=["click(btn)", "fill(name, John)"],
            recent_results=["ok", "ok"],
            errors_so_far=["step 1: timeout"],
            current_url="file:///test.txt",
            current_title="Test",
        )
        d = ctx.to_dict()
        assert d["prev_action"] == "click(btn)"
        assert len(d["recent_actions"]) == 2
        assert d["current_url"] == "file:///test.txt"


# ---------------------------------------------------------------------------
# build_step_context
# ---------------------------------------------------------------------------

class FakeStep:
    def __init__(self, step_number=1, action_name="click", action_params=None, error=None):
        self.step_number = step_number
        self.action_name = action_name
        self.action_params = action_params or {"target": "Btn"}
        self.error = error


class TestBuildStepContext:
    def test_empty_steps(self):
        ctx = build_step_context([])
        assert ctx.prev_action == ""
        assert not ctx.has_context

    def test_single_step(self):
        steps = [FakeStep(step_number=1, action_name="click", action_params={"target": "Submit"})]
        ctx = build_step_context(steps)
        assert "click(Submit)" in ctx.prev_action
        assert ctx.prev_result == "ok"

    def test_failed_step(self):
        steps = [FakeStep(step_number=1, action_name="click", error="not_found")]
        ctx = build_step_context(steps)
        assert "failed: not_found" in ctx.prev_result

    def test_multiple_steps(self):
        steps = [
            FakeStep(step_number=1, action_name="click", action_params={"target": "A"}),
            FakeStep(step_number=2, action_name="fill", action_params={"target": "B", "value": "hello"}),
            FakeStep(step_number=3, action_name="key_press", action_params={"key": "Enter"}),
        ]
        ctx = build_step_context(steps)
        assert len(ctx.recent_actions) == 3
        assert "key_press(Enter)" in ctx.prev_action

    def test_errors_collected(self):
        steps = [
            FakeStep(step_number=1, action_name="click", error="not_found"),
            FakeStep(step_number=2, action_name="click", action_params={"target": "Btn"}),
            FakeStep(step_number=3, action_name="fill", error="timeout"),
        ]
        ctx = build_step_context(steps)
        assert len(ctx.errors_so_far) == 2
        assert "step 1: not_found" in ctx.errors_so_far[0]

    def test_max_actions_limit(self):
        steps = [FakeStep(step_number=i, action_name="click") for i in range(10)]
        ctx = build_step_context(steps, max_actions=3)
        assert len(ctx.recent_actions) == 3

    def test_with_url_and_title(self):
        steps = [FakeStep()]
        ctx = build_step_context(steps, current_url="file:///doc.txt", current_title="Doc")
        assert ctx.current_url == "file:///doc.txt"
        assert ctx.current_title == "Doc"


# ---------------------------------------------------------------------------
# _format_action
# ---------------------------------------------------------------------------

class TestFormatAction:
    def test_action_with_target(self):
        step = FakeStep(action_name="click", action_params={"target": "Submit"})
        assert _format_action(step) == "click(Submit)"

    def test_action_with_text(self):
        step = FakeStep(action_name="type_text", action_params={"text": "hello"})
        assert _format_action(step) == "type_text(hello)"

    def test_action_with_key(self):
        step = FakeStep(action_name="key_press", action_params={"key": "Enter"})
        assert _format_action(step) == "key_press(Enter)"

    def test_action_no_params(self):
        step = FakeStep(action_name="screenshot", action_params={})
        # FakeStep defaults target to "Btn" if not overridden, so override
        step.action_params = {}
        assert _format_action(step) == "screenshot"

    def test_action_with_url(self):
        step = FakeStep(action_name="navigate", action_params={"url": "https://example.com"})
        assert _format_action(step) == "navigate(https://example.com)"
