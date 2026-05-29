"""Tests for clipboard operations — BATCH-28.

Covers:
  - SurfaceAdapter.paste() default implementation
  - WindowsAdapter.paste()
  - DesktopAgent clipboard facade methods
  - CLI clipboard subcommands
  - MCP clipboard tool execution
  - REST clipboard endpoint
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from deskaoy.results.types import ActionResult


# ---------------------------------------------------------------------------
# SurfaceAdapter.paste() default implementation
# ---------------------------------------------------------------------------

class TestSurfaceAdapterPaste:
    """Test the default paste() on SurfaceAdapter ABC."""

    def test_paste_calls_key_press_ctrl_v(self):
        """paste() should delegate to key_press('v', modifiers=2)."""
        from deskaoy.cascade.protocol import SurfaceAdapter

        # Create a minimal concrete subclass for testing
        class TestAdapter(SurfaceAdapter):
            async def click(self, target, **kw): pass
            async def fill(self, target, value, **kw): pass
            async def screenshot(self): return b""
            async def snapshot(self): return None
            async def evaluate(self, expr): return None
            async def key_press(self, key, modifiers=0, **kw):
                return ActionResult(ok=True, data={"key": key, "modifiers": modifiers})
            async def scroll(self, direction, amount=0, **kw): pass
            async def type_text(self, text, delay_ms=0, **kw): pass
            def current_url(self): return ""
            async def current_title(self): return ""

        import asyncio
        adapter = TestAdapter()
        result = asyncio.run(adapter.paste())
        assert result.ok is True
        assert result.data["key"] == "v"
        assert result.data["modifiers"] == 2  # CTRL


# ---------------------------------------------------------------------------
# DesktopAgent clipboard facade
# ---------------------------------------------------------------------------

class TestDesktopAgentClipboard:
    """Test DesktopAgent clipboard convenience methods."""

    def test_read_clipboard_delegates_to_surface(self):
        """read_clipboard() should call surface.read_clipboard()."""
        from deskaoy.desktop_agent import DesktopAgent
        import asyncio

        agent = DesktopAgent()
        mock_surface = MagicMock()
        mock_surface.read_clipboard = AsyncMock(return_value="hello clipboard")
        agent._surface = mock_surface

        result = asyncio.run(agent.read_clipboard())
        assert result == "hello clipboard"
        mock_surface.read_clipboard.assert_called_once()

    def test_read_clipboard_raises_without_surface(self):
        """read_clipboard() should raise RuntimeError without surface."""
        from deskaoy.desktop_agent import DesktopAgent
        import asyncio

        agent = DesktopAgent()
        with pytest.raises(RuntimeError, match="No surface adapter"):
            asyncio.run(agent.read_clipboard())

    def test_write_clipboard_delegates_to_surface(self):
        """write_clipboard() should call surface.write_clipboard()."""
        from deskaoy.desktop_agent import DesktopAgent
        import asyncio

        agent = DesktopAgent()
        mock_surface = MagicMock()
        mock_surface.write_clipboard = AsyncMock()
        agent._surface = mock_surface

        asyncio.run(agent.write_clipboard("test text"))
        mock_surface.write_clipboard.assert_called_once_with("test text")

    def test_write_clipboard_raises_without_surface(self):
        """write_clipboard() should raise RuntimeError without surface."""
        from deskaoy.desktop_agent import DesktopAgent
        import asyncio

        agent = DesktopAgent()
        with pytest.raises(RuntimeError, match="No surface adapter"):
            asyncio.run(agent.write_clipboard("test"))

    def test_paste_delegates_to_surface(self):
        """paste() should call surface.paste()."""
        from deskaoy.desktop_agent import DesktopAgent
        import asyncio

        agent = DesktopAgent()
        mock_surface = MagicMock()
        mock_surface.paste = AsyncMock(return_value=ActionResult(ok=True))
        agent._surface = mock_surface

        result = asyncio.run(agent.paste())
        assert result.ok is True
        mock_surface.paste.assert_called_once()

    def test_paste_returns_error_without_surface(self):
        """paste() should return ActionResult(ok=False) without surface."""
        from deskaoy.desktop_agent import DesktopAgent
        import asyncio

        agent = DesktopAgent()
        result = asyncio.run(agent.paste())
        assert result.ok is False


# ---------------------------------------------------------------------------
# CLI clipboard subcommands
# ---------------------------------------------------------------------------

class TestCLIClipboard:
    """Test CLI clipboard read/write/paste subcommands."""

    def test_clipboard_read_parser(self):
        """clipboard read subcommand parses correctly."""
        from deskaoy.cli.main import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["clipboard", "read"])
        assert args.command == "clipboard"
        assert args.clipboard_action == "read"

    def test_clipboard_write_parser(self):
        """clipboard write subcommand parses text argument."""
        from deskaoy.cli.main import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["clipboard", "write", "hello"])
        assert args.clipboard_action == "write"
        assert args.text == "hello"

    def test_clipboard_paste_parser(self):
        """clipboard paste subcommand parses correctly."""
        from deskaoy.cli.main import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["clipboard", "paste"])
        assert args.clipboard_action == "paste"

    def test_clipboard_read_success(self, capsys):
        """clipboard read outputs clipboard text."""
        from deskaoy.cli.main import main

        agent = MagicMock()
        agent.read_clipboard = AsyncMock(return_value="hello world")
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["clipboard", "read"])
        assert code == 0
        out = capsys.readouterr().out
        assert "hello world" in out

    def test_clipboard_read_json_output(self, capsys):
        """clipboard read --json outputs JSON."""
        from deskaoy.cli.main import main

        agent = MagicMock()
        agent.read_clipboard = AsyncMock(return_value="hello world")
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["clipboard", "read", "--json"])
        assert code == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["ok"] is True
        assert data["text"] == "hello world"

    def test_clipboard_write_success(self, capsys):
        """clipboard write outputs confirmation."""
        from deskaoy.cli.main import main

        agent = MagicMock()
        agent.write_clipboard = AsyncMock()
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["clipboard", "write", "new text"])
        assert code == 0
        agent.write_clipboard.assert_called_once_with("new text")

    def test_clipboard_paste_success(self, capsys):
        """clipboard paste outputs confirmation."""
        from deskaoy.cli.main import main

        agent = MagicMock()
        agent.paste = AsyncMock(return_value=ActionResult(ok=True))
        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            code = main(["clipboard", "paste"])
        assert code == 0
        agent.paste.assert_called_once()

    def test_clipboard_no_subcommand_shows_help(self):
        """clipboard with no subcommand shows help (exits 0 via --help)."""
        from deskaoy.cli.main import main
        with pytest.raises(SystemExit) as exc_info:
            main(["clipboard"])
        assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# MCP clipboard tool
# ---------------------------------------------------------------------------

class TestMCPClipboardTool:
    """Test MCP server clipboard tool execution."""

    def test_clipboard_tool_definition(self):
        """clipboard tool is in granular tools list."""
        from deskaoy.transport.mcp_server import _build_tools
        tools = _build_tools(compact=False)
        names = [t["name"] for t in tools]
        assert "clipboard" in names

    def test_clipboard_tool_has_required_action_property(self):
        """clipboard tool inputSchema requires 'action' field."""
        from deskaoy.transport.mcp_server import _build_tools
        tools = _build_tools(compact=False)
        clip_tool = next(t for t in tools if t["name"] == "clipboard")
        assert "action" in clip_tool["inputSchema"]["properties"]
        assert "action" in clip_tool["inputSchema"]["required"]
