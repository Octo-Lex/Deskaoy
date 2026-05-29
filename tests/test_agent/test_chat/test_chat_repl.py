"""Tests for AgentChat REPL — BATCH-29 TASK-01.

Covers:
  - /help command
  - /observe command
  - /click command (with and without target)
  - /type command (with and without text)
  - /snapshot command
  - /screenshot command
  - /exit command
  - Unknown command
  - Free-text instruction dispatch
  - REPL loop with input/output mock
  - EOFError exits gracefully
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from deskaoy.os_types import AgentResult, ResultStatus, Confidence
from deskaoy.agent.chat import AgentChat, ChatResult


# ---------------------------------------------------------------------------
# Mock agent
# ---------------------------------------------------------------------------

def _mock_agent() -> MagicMock:
    agent = MagicMock()
    result = AgentResult(
        execution_id="test",
        status=ResultStatus.SUCCESS,
        summary="test ok",
        confidence=Confidence(score=0.9, reason="test"),
    )
    agent.execute = AsyncMock(return_value=result)
    return agent


def _success_result() -> AgentResult:
    return AgentResult(
        execution_id="test",
        status=ResultStatus.SUCCESS,
        summary="action ok",
        confidence=Confidence(score=0.9, reason="test"),
    )


# ---------------------------------------------------------------------------
# T29-01: /help lists all commands
# ---------------------------------------------------------------------------

class TestChatHelp:

    @pytest.mark.asyncio
    async def test_help_lists_commands(self):
        agent = _mock_agent()
        chat = AgentChat(agent)
        result = await chat.process_command("/help")
        assert result.ok is True
        assert "/help" in result.output
        assert "/click" in result.output
        assert "/type" in result.output
        assert "/snapshot" in result.output
        assert "/screenshot" in result.output
        assert "/exit" in result.output


# ---------------------------------------------------------------------------
# T29-02: /click with target delegates to agent
# ---------------------------------------------------------------------------

class TestChatClick:

    @pytest.mark.asyncio
    async def test_click_with_target(self):
        agent = _mock_agent()
        chat = AgentChat(agent)
        result = await chat.process_command("/click OK button")
        assert result.ok is True
        assert "OK" in result.output
        agent.execute.assert_called_once()
        goal = agent.execute.call_args[0][0]
        assert goal.capability == "click"
        assert goal.params["target"] == "OK button"

    @pytest.mark.asyncio
    async def test_click_without_target_returns_error(self):
        agent = _mock_agent()
        chat = AgentChat(agent)
        result = await chat.process_command("/click")
        assert result.ok is False
        assert "Usage" in result.output


# ---------------------------------------------------------------------------
# T29-03: /type with text delegates to agent
# ---------------------------------------------------------------------------

class TestChatType:

    @pytest.mark.asyncio
    async def test_type_with_text(self):
        agent = _mock_agent()
        chat = AgentChat(agent)
        result = await chat.process_command("/type Hello World")
        assert result.ok is True
        agent.execute.assert_called_once()
        goal = agent.execute.call_args[0][0]
        assert goal.capability == "type_text"
        assert goal.params["text"] == "Hello World"

    @pytest.mark.asyncio
    async def test_type_without_text_returns_error(self):
        agent = _mock_agent()
        chat = AgentChat(agent)
        result = await chat.process_command("/type")
        assert result.ok is False
        assert "Usage" in result.output


# ---------------------------------------------------------------------------
# T29-04: /snapshot delegates to agent
# ---------------------------------------------------------------------------

class TestChatSnapshot:

    @pytest.mark.asyncio
    async def test_snapshot(self):
        agent = _mock_agent()
        chat = AgentChat(agent)
        result = await chat.process_command("/snapshot")
        assert result.ok is True
        agent.execute.assert_called_once()
        goal = agent.execute.call_args[0][0]
        assert goal.capability == "snapshot"


# ---------------------------------------------------------------------------
# T29-05: /screenshot delegates to agent
# ---------------------------------------------------------------------------

class TestChatScreenshot:

    @pytest.mark.asyncio
    async def test_screenshot(self):
        agent = _mock_agent()
        chat = AgentChat(agent)
        result = await chat.process_command("/screenshot")
        assert result.ok is True
        agent.execute.assert_called_once()
        goal = agent.execute.call_args[0][0]
        assert goal.capability == "screenshot"


# ---------------------------------------------------------------------------
# T29-06: /observe runs observation pipeline
# ---------------------------------------------------------------------------

class TestChatObserve:

    @pytest.mark.asyncio
    async def test_observe_success(self):
        agent = _mock_agent()
        chat = AgentChat(agent)

        mock_obs_result = MagicMock()
        mock_obs_result.element_count = 42
        mock_obs_result.steps_completed = ["screenshot", "ax_tree"]
        mock_obs_result.steps_skipped = []
        mock_obs_result.observation = MagicMock(active_window="Notepad")
        mock_obs_result.snapshot_id = "snap-123"

        mock_pipeline_instance = MagicMock()
        mock_pipeline_instance.observe = AsyncMock(return_value=mock_obs_result)

        with patch("deskaoy.observation_pipeline.ObservationPipeline", return_value=mock_pipeline_instance):
            result = await chat.process_command("/observe")

        assert result.ok is True
        assert "42" in result.output
        assert result.data["element_count"] == 42


# ---------------------------------------------------------------------------
# T29-07: /exit stops the REPL
# ---------------------------------------------------------------------------

class TestChatExit:

    @pytest.mark.asyncio
    async def test_exit_stops_repl(self):
        agent = _mock_agent()
        chat = AgentChat(agent)
        assert chat._running is False  # not started yet
        chat._running = True
        result = await chat.process_command("/exit")
        assert result.ok is True
        assert chat._running is False

    @pytest.mark.asyncio
    async def test_quit_also_exits(self):
        agent = _mock_agent()
        chat = AgentChat(agent)
        chat._running = True
        result = await chat.process_command("/quit")
        assert result.ok is True
        assert chat._running is False


# ---------------------------------------------------------------------------
# T29-08: Unknown command returns error
# ---------------------------------------------------------------------------

class TestChatUnknownCommand:

    @pytest.mark.asyncio
    async def test_unknown_command(self):
        agent = _mock_agent()
        chat = AgentChat(agent)
        result = await chat.process_command("/foobar")
        assert result.ok is False
        assert "Unknown command" in result.output


# ---------------------------------------------------------------------------
# T29-09: Free-text dispatches to automate
# ---------------------------------------------------------------------------

class TestChatFreeText:

    @pytest.mark.asyncio
    async def test_free_text_dispatches_to_automate(self):
        agent = _mock_agent()
        chat = AgentChat(agent)
        result = await chat.process_command("Open Notepad and type Hello")
        assert result.ok is True
        agent.execute.assert_called_once()
        goal = agent.execute.call_args[0][0]
        assert goal.capability == "automate"
        assert goal.params["instruction"] == "Open Notepad and type Hello"


# ---------------------------------------------------------------------------
# T29-10: REPL loop exits on /exit
# ---------------------------------------------------------------------------

class TestChatREPLLoop:

    @pytest.mark.asyncio
    async def test_repl_loop_exit(self):
        agent = _mock_agent()
        outputs = []
        chat = AgentChat(
            agent,
            input_fn=lambda prompt: "/exit",
            output_fn=lambda msg: outputs.append(msg),
        )
        code = await chat.run()
        assert code == 0
        # Should have printed "Goodbye!"
        assert any("Goodbye" in o for o in outputs)

    @pytest.mark.asyncio
    async def test_repl_loop_eof_exits(self):
        agent = _mock_agent()
        outputs = []
        chat = AgentChat(
            agent,
            input_fn=MagicMock(side_effect=EOFError),
            output_fn=lambda msg: outputs.append(msg),
        )
        code = await chat.run()
        assert code == 0
