"""BATCH-21: CUA Loop live integration + parser tests."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from deskaoy.agent.cua_loop import (
    CUAAction,
    CUALoop,
    CUAProvider,
    parse_anthropic_cua_response,
    parse_openai_cua_response,
)


class TestCUAStubMode:
    """Tests that work without API keys."""

    @pytest.mark.asyncio
    async def test_stub_mode_no_api_key(self):
        """TEST-21-01: CUA loop stub mode still works without API key."""
        loop = CUALoop(adapter=None, provider=CUAProvider.OPENAI)
        result = await loop.run("Open Notepad")
        assert result.total_steps >= 1
        assert result.completion_reason == "success"

    @pytest.mark.asyncio
    async def test_no_adapter_returns_empty_screenshot(self):
        """TEST-21-02: _get_proposal returns DONE when no adapter."""
        loop = CUALoop(adapter=None, api_key="")
        proposal = await loop._get_proposal("test", "", [])
        assert proposal.done is True


class TestResponseParsers:
    """Test response parsers with real API response formats."""

    def test_openai_tool_calls_format(self):
        """TEST-21-03: OpenAI parser handles tool_calls format."""
        response = {
            "tool_calls": [{
                "function": {
                    "name": "computer_use_preview",
                    "arguments": {
                        "action": "click",
                        "coordinate": [100, 200],
                    }
                }
            }]
        }
        proposal = parse_openai_cua_response(response)
        assert proposal.action == CUAAction.CLICK
        assert proposal.params["x"] == 100
        assert proposal.params["y"] == 200

    def test_anthropic_content_blocks_format(self):
        """TEST-21-04: Anthropic parser handles content blocks."""
        response = {
            "content": [{
                "type": "tool_use",
                "name": "computer_20241022",
                "input": {
                    "action": "left_click",
                    "coordinate": [300, 400],
                }
            }]
        }
        proposal = parse_anthropic_cua_response(response)
        assert proposal.action == CUAAction.CLICK
        assert proposal.params["x"] == 300

    @pytest.mark.asyncio
    async def test_execute_action_click(self):
        """TEST-21-05: _execute_action dispatches click correctly."""
        adapter = AsyncMock()
        adapter.click.return_value = MagicMock(ok=True)
        loop = CUALoop(adapter=adapter)
        from deskaoy.agent.cua_loop import CUAActionProposal
        proposal = CUAActionProposal(action=CUAAction.CLICK, params={"x": 100, "y": 200})
        await loop._execute_action(proposal)
        adapter.click.assert_called_once_with("100,200")


# ---------------------------------------------------------------------------
# Live integration tests (require API keys)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="No OPENAI_API_KEY")
class TestLiveOpenAICUA:
    @pytest.mark.asyncio
    async def test_live_openai_cua(self):
        """TEST-21-06: Live CUA loop with OpenAI."""
        import subprocess
        import time

        import win32con
        import win32gui

        from deskaoy.adapters.windows import WindowsAdapter

        proc = subprocess.Popen(["notepad.exe"])
        time.sleep(2.0)
        hwnd = win32gui.FindWindow("Notepad", None)
        if not hwnd:
            proc.terminate()
            pytest.skip("Notepad not found")

        try:
            adapter = WindowsAdapter(hwnd=hwnd)
            loop = CUALoop(
                adapter=adapter,
                provider=CUAProvider.OPENAI,
                api_key=os.environ["OPENAI_API_KEY"],
                max_steps=3,
            )
            result = await loop.run("Type Hello in Notepad")
            assert result.total_steps >= 1
            assert result.provider == CUAProvider.OPENAI
        finally:
            try:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                time.sleep(0.5)
            except Exception:
                pass
            proc.terminate()


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="No ANTHROPIC_API_KEY")
class TestLiveAnthropicCUA:
    @pytest.mark.asyncio
    async def test_live_anthropic_cua(self):
        """TEST-21-07: Live CUA loop with Anthropic."""
        import subprocess
        import time

        import win32con
        import win32gui

        from deskaoy.adapters.windows import WindowsAdapter

        proc = subprocess.Popen(["notepad.exe"])
        time.sleep(2.0)
        hwnd = win32gui.FindWindow("Notepad", None)
        if not hwnd:
            proc.terminate()
            pytest.skip("Notepad not found")

        try:
            adapter = WindowsAdapter(hwnd=hwnd)
            loop = CUALoop(
                adapter=adapter,
                provider=CUAProvider.ANTHROPIC,
                api_key=os.environ["ANTHROPIC_API_KEY"],
                max_steps=3,
            )
            result = await loop.run("Type Hello in Notepad")
            assert result.total_steps >= 1
            assert result.provider == CUAProvider.ANTHROPIC
        finally:
            try:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                time.sleep(0.5)
            except Exception:
                pass
            proc.terminate()
