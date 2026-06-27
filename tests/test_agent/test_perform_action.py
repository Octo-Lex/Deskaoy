"""Tests for perform_action facade, CLI, MCP, and REST — BATCH-28.

Covers:
  - DesktopAgent.perform_action() facade delegation
  - DesktopAgent.perform_action() dry_run mode
  - DesktopAgent.perform_action() without surface
  - CLI perform-action command parsing and execution
  - MCP perform_action tool
  - REST perform-action endpoint routing
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deskaoy.results.types import ActionResult

# ---------------------------------------------------------------------------
# DesktopAgent.perform_action() facade
# ---------------------------------------------------------------------------

class TestDesktopAgentPerformAction:
    """Test DesktopAgent.perform_action() facade method."""

    def test_perform_action_delegates_to_invoke_element(self):
        """perform_action() should call surface.invoke_element."""
        import asyncio

        from deskaoy.desktop_agent import DesktopAgent

        agent = DesktopAgent()
        mock_surface = MagicMock()
        mock_surface.invoke_element = AsyncMock(return_value=ActionResult(
            ok=True, data={"pattern_used": "InvokePattern", "action": "invoke"},
        ))
        agent._surface = mock_surface

        result = asyncio.run(agent.perform_action("name:Button", "invoke"))
        assert result.ok is True
        mock_surface.invoke_element.assert_called_once_with(
            "name:Button", action="invoke", value="",
        )

    def test_perform_action_with_value(self):
        """perform_action() forwards value to invoke_element."""
        import asyncio

        from deskaoy.desktop_agent import DesktopAgent

        agent = DesktopAgent()
        mock_surface = MagicMock()
        mock_surface.invoke_element = AsyncMock(return_value=ActionResult(
            ok=True, data={"pattern_used": "ValuePattern"},
        ))
        agent._surface = mock_surface

        result = asyncio.run(agent.perform_action(
            "name:Input", "set_value", value="hello",
        ))
        assert result.ok is True
        mock_surface.invoke_element.assert_called_once_with(
            "name:Input", action="set_value", value="hello",
        )

    def test_perform_action_dry_run(self):
        """perform_action(dry_run=True) returns without executing."""
        import asyncio

        from deskaoy.desktop_agent import DesktopAgent

        agent = DesktopAgent()
        mock_surface = MagicMock()
        mock_surface.invoke_element = AsyncMock()
        agent._surface = mock_surface

        result = asyncio.run(agent.perform_action(
            "name:Button", "toggle", dry_run=True,
        ))
        assert result.ok is True
        assert result.data["dry_run"] is True
        assert result.data["action"] == "perform_action"
        mock_surface.invoke_element.assert_not_called()

    def test_perform_action_without_surface(self):
        """perform_action() returns error without surface adapter."""
        import asyncio

        from deskaoy.desktop_agent import DesktopAgent

        agent = DesktopAgent()
        result = asyncio.run(agent.perform_action("name:Btn", "invoke"))
        assert result.ok is False
        assert "No surface adapter" in str(result.data.get("error", ""))

    def test_perform_action_toggle(self):
        """perform_action('toggle') dispatches correctly."""
        import asyncio

        from deskaoy.desktop_agent import DesktopAgent

        agent = DesktopAgent()
        mock_surface = MagicMock()
        mock_surface.invoke_element = AsyncMock(return_value=ActionResult(
            ok=True, data={"pattern_used": "TogglePattern"},
        ))
        agent._surface = mock_surface

        result = asyncio.run(agent.perform_action("name:Checkbox", "toggle"))
        assert result.ok is True
        assert result.data["pattern_used"] == "TogglePattern"

    def test_perform_action_expand(self):
        """perform_action('expand') dispatches correctly."""
        import asyncio

        from deskaoy.desktop_agent import DesktopAgent

        agent = DesktopAgent()
        mock_surface = MagicMock()
        mock_surface.invoke_element = AsyncMock(return_value=ActionResult(
            ok=True, data={"pattern_used": "ExpandCollapsePattern"},
        ))
        agent._surface = mock_surface

        result = asyncio.run(agent.perform_action("name:TreeItem", "expand"))
        assert result.ok is True


# ---------------------------------------------------------------------------
# CLI perform-action command
# ---------------------------------------------------------------------------

class TestCLIPerformAction:
    """Test CLI perform-action command."""

    def test_perform_action_parser(self):
        """perform-action parses target and action arguments."""
        from deskaoy.cli.main import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["perform-action", "name:Btn", "invoke"])
        assert args.command == "perform-action"
        assert args.target == "name:Btn"
        assert args.action == "invoke"

    def test_perform_action_value_flag(self):
        """perform-action --value passes value argument."""
        from deskaoy.cli.main import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["perform-action", "name:Input", "set_value", "--value", "hello"])
        assert args.value == "hello"

    def test_perform_action_dry_run_flag(self):
        """perform-action --dry-run sets dry_run=True."""
        from deskaoy.cli.main import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["perform-action", "--dry-run", "name:Btn", "toggle"])
        assert args.dry_run is True

    def test_perform_action_success(self, capsys):
        """perform-action command outputs success."""
        from deskaoy.cli.main import main

        agent = MagicMock()
        agent.perform_action = AsyncMock(return_value=ActionResult(
            ok=True, data={"pattern_used": "InvokePattern"},
        ))
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["perform-action", "name:Btn", "invoke"])
        assert code == 0
        agent.perform_action.assert_called_once_with(
            "name:Btn", "invoke", value="", dry_run=False,
        )

    def test_perform_action_json_output(self, capsys):
        """perform-action with --json outputs JSON."""
        from deskaoy.cli.main import main

        agent = MagicMock()
        agent.perform_action = AsyncMock(return_value=ActionResult(
            ok=True, data={"pattern_used": "TogglePattern"},
        ))
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["--json", "perform-action", "name:Cb", "toggle"])
        assert code == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["ok"] is True

    def test_perform_action_failure(self, capsys):
        """perform-action with failed result exits 1."""
        from deskaoy.cli.main import main
        from deskaoy.results.types import ActionError, ErrorCategory

        agent = MagicMock()
        agent.perform_action = AsyncMock(return_value=ActionResult(
            ok=False, error=ActionError(ErrorCategory.VALIDATION, "unknown action"),
        ))
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["perform-action", "name:Btn", "unknown_action"])
        assert code == 1


# ---------------------------------------------------------------------------
# MCP perform_action tool
# ---------------------------------------------------------------------------

class TestMCPPerformActionTool:
    """Test MCP server perform_action tool."""

    def test_perform_action_tool_definition(self):
        """perform_action tool is in granular tools list."""
        from deskaoy.transport.mcp_server import _build_tools
        tools = _build_tools(compact=False)
        names = [t["name"] for t in tools]
        assert "perform_action" in names

    def test_perform_action_requires_target_and_action(self):
        """perform_action tool requires 'target' and 'action' in inputSchema."""
        from deskaoy.transport.mcp_server import _build_tools
        tools = _build_tools(compact=False)
        tool = next(t for t in tools if t["name"] == "perform_action")
        required = tool["inputSchema"]["required"]
        assert "target" in required
        assert "action" in required

    def test_perform_action_execution(self):
        """MCP _execute_perform_action routes to agent.perform_action."""
        import asyncio

        from deskaoy.transport.mcp_server import MCPServer

        server = MCPServer()
        mock_agent = MagicMock()
        mock_agent.perform_action = AsyncMock(return_value=ActionResult(
            ok=True, data={"pattern_used": "InvokePattern"},
        ))
        server._agent = mock_agent

        result = asyncio.run(server._execute_perform_action({
            "target": "name:Button",
            "action": "invoke",
        }))
        assert result["ok"] is True
        mock_agent.perform_action.assert_called_once()


# ---------------------------------------------------------------------------
# REST endpoint routing
# ---------------------------------------------------------------------------

class TestRESTPerformActionRoute:
    """Test REST server perform-action route is registered."""

    def test_perform_action_route_registered(self):
        """POST /perform-action route exists in the REST app."""
        try:
            from deskaoy.transport.rest_server import create_app
            app = create_app()
            if app is None:
                pytest.skip("aiohttp not installed")
            routes = [r.resource.canonical for r in app.router.routes()
                      if hasattr(r, 'resource') and r.resource is not None]
            assert "/perform-action" in routes
        except ImportError:
            pytest.skip("aiohttp not installed")

    def test_clipboard_route_registered(self):
        """POST /clipboard route exists in the REST app."""
        try:
            from deskaoy.transport.rest_server import create_app
            app = create_app()
            if app is None:
                pytest.skip("aiohttp not installed")
            routes = [r.resource.canonical for r in app.router.routes()
                      if hasattr(r, 'resource') and r.resource is not None]
            assert "/clipboard" in routes
        except ImportError:
            pytest.skip("aiohttp not installed")

    def test_set_value_route_registered(self):
        """POST /set-value route exists in the REST app."""
        try:
            from deskaoy.transport.rest_server import create_app
            app = create_app()
            if app is None:
                pytest.skip("aiohttp not installed")
            routes = [r.resource.canonical for r in app.router.routes()
                      if hasattr(r, 'resource') and r.resource is not None]
            assert "/set-value" in routes
        except ImportError:
            pytest.skip("aiohttp not installed")
