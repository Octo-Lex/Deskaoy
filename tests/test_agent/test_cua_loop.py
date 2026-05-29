"""Tests for CUA Loop (BATCH-08)."""
from __future__ import annotations

import asyncio
import pytest

from deskaoy.agent.cua_loop import (
    CUALoop,
    CUAAction,
    CUAProvider,
    CUAStep,
    CUALoopResult,
    CUAActionProposal,
    parse_openai_cua_response,
    parse_anthropic_cua_response,
)


# ---------------------------------------------------------------------------
# Response Parser Tests
# ---------------------------------------------------------------------------

class TestOpenAICUAParser:
    def test_click_action(self):
        response = {
            "tool_calls": [{
                "function": {
                    "name": "computer_use_preview",
                    "arguments": {"action": "click", "coordinate": [100, 200]},
                }
            }]
        }
        proposal = parse_openai_cua_response(response)
        assert proposal.action == CUAAction.CLICK
        assert proposal.params["x"] == 100
        assert proposal.params["y"] == 200

    def test_type_action(self):
        response = {
            "tool_calls": [{
                "function": {
                    "name": "computer_use_preview",
                    "arguments": {"action": "type", "text": "Hello World"},
                }
            }]
        }
        proposal = parse_openai_cua_response(response)
        assert proposal.action == CUAAction.TYPE
        assert proposal.params["text"] == "Hello World"

    def test_key_action(self):
        response = {
            "tool_calls": [{
                "function": {
                    "name": "computer_use_preview",
                    "arguments": {"action": "key", "key": "Enter"},
                }
            }]
        }
        proposal = parse_openai_cua_response(response)
        assert proposal.action == CUAAction.KEY
        assert proposal.params["key"] == "Enter"

    def test_done_when_no_tool_calls(self):
        response = {"content": "Task complete!"}
        proposal = parse_openai_cua_response(response)
        assert proposal.done is True

    def test_arguments_string_parsed(self):
        response = {
            "tool_calls": [{
                "function": {
                    "name": "computer_use_preview",
                    "arguments": '{"action": "click", "coordinate": [50, 75]}',
                }
            }]
        }
        proposal = parse_openai_cua_response(response)
        assert proposal.action == CUAAction.CLICK
        assert proposal.params["x"] == 50


class TestAnthropicCUAParser:
    def test_left_click(self):
        response = {
            "content": [{
                "type": "tool_use",
                "name": "computer_20241022",
                "input": {"action": "left_click", "coordinate": [300, 400]},
            }]
        }
        proposal = parse_anthropic_cua_response(response)
        assert proposal.action == CUAAction.CLICK
        assert proposal.params["x"] == 300

    def test_type_text(self):
        response = {
            "content": [{
                "type": "tool_use",
                "name": "computer_20241022",
                "input": {"action": "type", "text": "hello"},
            }]
        }
        proposal = parse_anthropic_cua_response(response)
        assert proposal.action == CUAAction.TYPE
        assert proposal.params["text"] == "hello"

    def test_scroll_down(self):
        response = {
            "content": [{
                "type": "tool_use",
                "name": "computer_20241022",
                "input": {"action": "scroll_down", "scroll_amount": 5},
            }]
        }
        proposal = parse_anthropic_cua_response(response)
        assert proposal.action == CUAAction.SCROLL
        assert proposal.params["direction"] == "down"
        assert proposal.params["amount"] == 5

    def test_text_block_means_done(self):
        response = {
            "content": [{"type": "text", "text": "The task is complete."}]
        }
        proposal = parse_anthropic_cua_response(response)
        assert proposal.done is True

    def test_empty_content_means_done(self):
        response = {"content": []}
        proposal = parse_anthropic_cua_response(response)
        assert proposal.done is True


# ---------------------------------------------------------------------------
# CUALoop Tests
# ---------------------------------------------------------------------------

class TestCUALoop:
    def test_constructor(self):
        loop = CUALoop(provider=CUAProvider.ANTHROPIC, max_steps=10)
        assert loop._provider == CUAProvider.ANTHROPIC
        assert loop._max_steps == 10

    def test_run_completes(self):
        """CUA loop runs and returns result (stub mode — immediately done)."""
        loop = CUALoop(max_steps=5)
        result = asyncio.run(loop.run("Test instruction"))
        assert isinstance(result, CUALoopResult)
        assert result.instruction == "Test instruction"
        assert result.total_steps >= 1
        assert result.completion_reason == "success"

    def test_result_has_provider(self):
        loop = CUALoop(provider=CUAProvider.OPENAI)
        result = asyncio.run(loop.run("test"))
        assert result.provider == CUAProvider.OPENAI

    def test_step_types(self):
        """CUAStep has expected fields."""
        step = CUAStep(step_number=1, action=CUAAction.CLICK, params={"x": 100, "y": 200}, duration_ms=50.0)
        assert step.action == CUAAction.CLICK
        assert step.error is None

    def test_proposal_types(self):
        """CUAActionProposal has expected fields."""
        proposal = CUAActionProposal(action=CUAAction.TYPE, params={"text": "hi"}, reasoning="typing greeting")
        assert proposal.done is False
        assert proposal.reasoning == "typing greeting"
