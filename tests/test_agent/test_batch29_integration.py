"""Tests for BATCH-29 TASK-03 — CLI chat/run commands, MCP tools, REST endpoints."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deskaoy.os_types import AgentResult, Confidence, ResultStatus

# Re-export for convenience in tests
_AgentResult = AgentResult
_ResultStatus = ResultStatus
_Confidence = Confidence


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _mock_agent() -> MagicMock:
    agent = MagicMock()

    result = AgentResult(
        execution_id="test",
        status=ResultStatus.SUCCESS,
        summary="action ok",
        confidence=Confidence(score=0.9, reason="test"),
    )
    agent.execute = AsyncMock(return_value=result)
    return result, agent


def _write_script(data: dict, tmp_path: Path) -> Path:
    p = tmp_path / "test.deskaoy.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# CLI: chat command
# ---------------------------------------------------------------------------

class TestCLIChatCommand:

    def test_chat_subcommand_parses(self):
        """deskaoy chat parses correctly."""
        from deskaoy.cli.main import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["chat"])
        assert args.command == "chat"

    @pytest.mark.asyncio
    async def test_chat_command_exits(self, capsys):
        """chat command runs AgentChat and exits with 0."""
        from deskaoy.cli.main import _cmd_chat

        mock_agent = MagicMock()
        with patch("deskaoy.cli.main._get_agent", return_value=mock_agent):
            with patch("deskaoy.agent.chat.AgentChat.run", new_callable=AsyncMock, return_value=0) as mock_run:
                args = MagicMock()
                args.storage_dir = None
                code = await _cmd_chat(args)

        assert code == 0
        mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# CLI: run command
# ---------------------------------------------------------------------------

class TestCLIRunCommand:

    def test_run_subcommand_parses(self):
        """deskaoy run parses script path and --dry-run."""
        from deskaoy.cli.main import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["run", "myscript.deskaoy.json"])
        assert args.command == "run"
        assert args.script == "myscript.deskaoy.json"
        assert args.dry_run is False

    def test_run_subcommand_dry_run(self):
        """deskaoy run --dry-run parses correctly."""
        from deskaoy.cli.main import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["run", "test.json", "--dry-run"])
        assert args.dry_run is True

    @pytest.mark.asyncio
    async def test_run_command_success(self, capsys, tmp_path):
        """run command executes script and outputs results."""
        from deskaoy.cli.main import _cmd_run

        script = _write_script({
            "name": "Test Script",
            "steps": [{"action": "snapshot"}],
        }, tmp_path)

        mock_result, mock_agent = _mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=mock_agent):
            args = MagicMock()
            args.script = str(script)
            args.dry_run = False
            args.json = False
            args.storage_dir = None
            code = await _cmd_run(args)

        assert code == 0
        out = capsys.readouterr().out
        assert "Test Script" in out

    @pytest.mark.asyncio
    async def test_run_command_json_output(self, capsys, tmp_path):
        """run command --json outputs structured JSON."""
        from deskaoy.cli.main import _cmd_run

        script = _write_script({
            "name": "JSON Test",
            "steps": [{"action": "snapshot"}],
        }, tmp_path)

        mock_result, mock_agent = _mock_agent()
        with patch("deskaoy.cli.main._get_agent", return_value=mock_agent):
            args = MagicMock()
            args.script = str(script)
            args.dry_run = False
            args.json = True
            args.storage_dir = None
            code = await _cmd_run(args)

        assert code == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["ok"] is True
        assert data["name"] == "JSON Test"
        assert "steps" in data


# ---------------------------------------------------------------------------
# MCP: chat_message tool
# ---------------------------------------------------------------------------

class TestMCPChatMessage:

    def test_chat_message_tool_in_list(self):
        """chat_message appears in granular tool list."""
        from deskaoy.transport.mcp_server import _build_tools
        tools = _build_tools(compact=False)
        names = [t["name"] for t in tools]
        assert "chat_message" in names

    @pytest.mark.asyncio
    async def test_chat_message_execution(self):
        """chat_message tool returns structured result."""
        from deskaoy.transport.mcp_server import MCPServer

        server = MCPServer(compact=False)
        result = await server._execute_chat_message({"message": "/help"})
        assert result["status"] == "success"
        assert "/help" in result["output"]


# ---------------------------------------------------------------------------
# MCP: run_script tool
# ---------------------------------------------------------------------------

class TestMCPRunScript:

    def test_run_script_tool_in_list(self):
        """run_script appears in granular tool list."""
        from deskaoy.transport.mcp_server import _build_tools
        tools = _build_tools(compact=False)
        names = [t["name"] for t in tools]
        assert "run_script" in names

    @pytest.mark.asyncio
    async def test_run_script_execution(self, tmp_path):
        """run_script tool executes a script file."""
        from deskaoy.transport.mcp_server import MCPServer

        script = _write_script({
            "name": "MCP Test",
            "steps": [{"action": "snapshot"}],
        }, tmp_path)

        server = MCPServer(compact=False)

        # Mock the agent so execute returns success
        mock_result = AgentResult(
            execution_id="mcp-test",
            status=ResultStatus.SUCCESS,
            summary="snapshot ok",
            confidence=Confidence(score=0.9, reason="test"),
        )
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=mock_result)
        server._agent = mock_agent

        result = await server._execute_run_script({"path": str(script)})
        assert result["status"] == "success"
        assert result["name"] == "MCP Test"
        assert result["steps_total"] == 1


# ---------------------------------------------------------------------------
# REST: /chat and /run-script endpoints
# ---------------------------------------------------------------------------

class TestRESTEndpoints:

    @pytest.fixture
    def app(self):
        """Create REST app."""
        from deskaoy.transport.rest_server import create_app
        application = create_app()
        if application is None:
            pytest.skip("aiohttp not installed")
        return application

    def test_chat_endpoint_registered(self, app):
        """POST /chat endpoint exists."""
        routes = []
        for r in app.router.routes():
            res = r.resource
            if res:
                routes.append(res.canonical)
        assert "/chat" in routes

    def test_run_script_endpoint_registered(self, app):
        """POST /run-script endpoint exists."""
        routes = []
        for r in app.router.routes():
            res = r.resource
            if res:
                routes.append(res.canonical)
        assert "/run-script" in routes
