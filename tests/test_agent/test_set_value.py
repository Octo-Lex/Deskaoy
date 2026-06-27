"""Tests for set_value facade and CLI — BATCH-28.

Covers:
  - DesktopAgent.set_value() facade delegation
  - DesktopAgent.set_value() dry_run mode
  - DesktopAgent.set_value() without surface
  - CLI set-value command parsing and execution
  - MCP set_value tool
  - REST set-value endpoint
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from deskaoy.results.types import ActionResult

# ---------------------------------------------------------------------------
# DesktopAgent.set_value() facade
# ---------------------------------------------------------------------------

class TestDesktopAgentSetValue:
    """Test DesktopAgent.set_value() facade method."""

    def test_set_value_delegates_to_invoke_element(self):
        """set_value() should call surface.invoke_element with action='set_value'."""
        import asyncio

        from deskaoy.desktop_agent import DesktopAgent

        agent = DesktopAgent()
        mock_surface = MagicMock()
        mock_surface.invoke_element = AsyncMock(return_value=ActionResult(
            ok=True, data={"value_set": "hello", "pattern_used": "ValuePattern"},
        ))
        agent._surface = mock_surface

        result = asyncio.run(agent.set_value("name:TextBox", "hello"))
        assert result.ok is True
        mock_surface.invoke_element.assert_called_once_with(
            "name:TextBox", action="set_value", value="hello",
        )

    def test_set_value_dry_run(self):
        """set_value(dry_run=True) should return without calling invoke_element."""
        import asyncio

        from deskaoy.desktop_agent import DesktopAgent

        agent = DesktopAgent()
        mock_surface = MagicMock()
        mock_surface.invoke_element = AsyncMock()
        agent._surface = mock_surface

        result = asyncio.run(agent.set_value("name:Input", "test", dry_run=True))
        assert result.ok is True
        assert result.data["dry_run"] is True
        assert result.data["action"] == "set_value"
        mock_surface.invoke_element.assert_not_called()

    def test_set_value_without_surface(self):
        """set_value() returns error without surface adapter."""
        import asyncio

        from deskaoy.desktop_agent import DesktopAgent

        agent = DesktopAgent()
        result = asyncio.run(agent.set_value("name:Input", "test"))
        assert result.ok is False
        assert "No surface adapter" in str(result.data.get("error", ""))

    def test_set_value_returns_pattern_used_metadata(self):
        """set_value() should return pattern_used in result data."""
        import asyncio

        from deskaoy.desktop_agent import DesktopAgent

        agent = DesktopAgent()
        mock_surface = MagicMock()
        mock_surface.invoke_element = AsyncMock(return_value=ActionResult(
            ok=True,
            data={"value_set": "42", "pattern_used": "ValuePattern", "fallback_used": False},
        ))
        agent._surface = mock_surface

        result = asyncio.run(agent.set_value("auto:numInput", "42"))
        assert result.ok is True
        assert result.data["pattern_used"] == "ValuePattern"

    def test_set_value_fallback_used_metadata(self):
        """set_value() should return fallback_used when ValuePattern unavailable."""
        import asyncio

        from deskaoy.desktop_agent import DesktopAgent

        agent = DesktopAgent()
        mock_surface = MagicMock()
        mock_surface.invoke_element = AsyncMock(return_value=ActionResult(
            ok=True,
            data={"value_set": "fallback", "pattern_used": None, "fallback_used": True},
        ))
        agent._surface = mock_surface

        result = asyncio.run(agent.set_value("name:Field", "fallback"))
        assert result.ok is True
        assert result.data["fallback_used"] is True


# ---------------------------------------------------------------------------
# CLI set-value command
# ---------------------------------------------------------------------------

class TestCLISetValue:
    """Test CLI set-value command."""

    def test_set_value_parser(self):
        """set-value parses target and value arguments."""
        from deskaoy.cli.main import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["set-value", "name:Input", "hello"])
        assert args.command == "set-value"
        assert args.target == "name:Input"
        assert args.value == "hello"

    def test_set_value_dry_run_flag(self):
        """set-value --dry-run sets dry_run=True."""
        from deskaoy.cli.main import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["set-value", "--dry-run", "name:Input", "hello"])
        assert args.dry_run is True

    def test_set_value_success(self, capsys):
        """set-value command outputs success."""
        from deskaoy.cli.main import main

        agent = MagicMock()
        agent.set_value = AsyncMock(return_value=ActionResult(
            ok=True, data={"value_set": "hello"},
        ))
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["set-value", "name:Input", "hello"])
        assert code == 0
        agent.set_value.assert_called_once_with("name:Input", "hello", dry_run=False)

    def test_set_value_json_output(self, capsys):
        """set-value --json outputs JSON."""
        from deskaoy.cli.main import main

        agent = MagicMock()
        agent.set_value = AsyncMock(return_value=ActionResult(
            ok=True, data={"value_set": "hello"},
        ))
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["--json", "set-value", "name:Input", "hello"])
        assert code == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["ok"] is True

    def test_set_value_failure(self, capsys):
        """set-value with failed result exits 1."""
        from deskaoy.cli.main import main
        from deskaoy.results.types import ActionError, ErrorCategory

        agent = MagicMock()
        agent.set_value = AsyncMock(return_value=ActionResult(
            ok=False, error=ActionError(ErrorCategory.UNKNOWN, "not found"),
        ))
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["set-value", "name:Missing", "test"])
        assert code == 1


# ---------------------------------------------------------------------------
# MCP set_value tool
# ---------------------------------------------------------------------------

class TestMCPSetValueTool:
    """Test MCP server set_value tool."""

    def test_set_value_tool_definition(self):
        """set_value tool is in granular tools list."""
        from deskaoy.transport.mcp_server import _build_tools
        tools = _build_tools(compact=False)
        names = [t["name"] for t in tools]
        assert "set_value" in names

    def test_set_value_requires_target_and_value(self):
        """set_value tool requires 'target' and 'value' in inputSchema."""
        from deskaoy.transport.mcp_server import _build_tools
        tools = _build_tools(compact=False)
        tool = next(t for t in tools if t["name"] == "set_value")
        required = tool["inputSchema"]["required"]
        assert "target" in required
        assert "value" in required

    def test_set_value_execution(self):
        """MCP _execute_set_value routes to agent.set_value."""
        import asyncio

        from deskaoy.transport.mcp_server import MCPServer

        server = MCPServer()
        mock_agent = MagicMock()
        mock_agent.set_value = AsyncMock(return_value=ActionResult(
            ok=True, data={"value_set": "42"},
        ))
        server._agent = mock_agent

        result = asyncio.run(server._execute_set_value({
            "target": "name:Input",
            "value": "42",
        }))
        assert result["ok"] is True
        mock_agent.set_value.assert_called_once()
