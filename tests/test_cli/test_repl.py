"""Tests for CLI REPL (T01-28 through T01-31)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deskaoy.cli.repl import run_repl
from deskaoy.os_types import (
    AgentResult,
    Confidence,
    ResultStatus,
)

# ---------------------------------------------------------------------------
# Mock agent
# ---------------------------------------------------------------------------

def _mock_agent():
    agent = MagicMock()

    result = AgentResult(
        execution_id="repl-exec",
        status=ResultStatus.SUCCESS,
        summary="REPL success",
        confidence=Confidence(score=0.95, reason="test"),
    )
    agent.execute = AsyncMock(return_value=result)
    agent.estimate = AsyncMock(return_value=MagicMock())

    health_status = MagicMock()
    health_status.healthy = True
    health_status.message = "OK"
    health_status.probes = {"adapter": True}
    agent.health_check = AsyncMock(return_value=health_status)

    agent.schema.return_value = {"capabilities": {}}
    agent.configure_session = MagicMock()
    agent.terminate_session = MagicMock()

    agent.fact_store = MagicMock()
    agent.fact_store.get_facts.return_value = []
    agent.fact_store.get_soul_aspects.return_value = []

    agent.skill_loader = MagicMock()
    agent.skill_loader.discover.return_value = []

    return agent


# ---------------------------------------------------------------------------
# T01-28: .help prints all dot-commands
# ---------------------------------------------------------------------------

class TestReplHelp:

    @pytest.mark.asyncio
    async def test_help_prints_commands(self, capsys):
        agent = _mock_agent()
        with patch("deskaoy.cli.repl._get_agent", return_value=agent):
            with patch("builtins.input", side_effect=[".help", ".exit"]):
                await run_repl(session_id="test-session")

        out = capsys.readouterr().out
        assert ".help" in out
        assert ".health" in out
        assert ".facts" in out
        assert ".exit" in out


# ---------------------------------------------------------------------------
# T01-29: .exit calls terminate_session
# ---------------------------------------------------------------------------

class TestReplExit:

    @pytest.mark.asyncio
    async def test_exit_calls_terminate(self, capsys):
        agent = _mock_agent()
        with patch("deskaoy.cli.repl._get_agent", return_value=agent):
            with patch("builtins.input", side_effect=[".exit"]):
                code = await run_repl(session_id="test-session")

        assert code == 0
        agent.terminate_session.assert_called_once_with("test-session")


# ---------------------------------------------------------------------------
# T01-30: normal instruction dispatches to execute
# ---------------------------------------------------------------------------

class TestReplInstruction:

    @pytest.mark.asyncio
    async def test_dispatches_to_execute(self, capsys):
        agent = _mock_agent()
        with patch("deskaoy.cli.repl._get_agent", return_value=agent):
            with patch("builtins.input", side_effect=["click OK button", ".exit"]):
                await run_repl(session_id="test-session")

        agent.execute.assert_called_once()
        out = capsys.readouterr().out
        assert "SUCCESS" in out


# ---------------------------------------------------------------------------
# T01-31: KeyboardInterrupt → terminate_session
# ---------------------------------------------------------------------------

class TestReplKeyboardInterrupt:

    @pytest.mark.asyncio
    async def test_ctrl_c_terminates_session(self, capsys):
        agent = _mock_agent()
        with patch("deskaoy.cli.repl._get_agent", return_value=agent):
            # First input raises KeyboardInterrupt
            with patch("builtins.input", side_effect=KeyboardInterrupt):
                code = await run_repl(session_id="test-session")

        assert code == 0
        agent.terminate_session.assert_called_once_with("test-session")
