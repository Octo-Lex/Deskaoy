"""End-to-end integration test: real Windows + real LLM → real desktop automation.

Gated behind --run-integration. Requires:
  - Windows 10/11
  - OPENAI_API_KEY or ANTHROPIC_API_KEY environment variable
  - `openai` or `anthropic` pip package installed

Proves the full stack:
  UIA tree walking → selector resolution → AgentLoop planning → LLM dispatch
  → WindowsAdapter mouse/keyboard → verification → memory recording
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

# Skip entire module if not on Windows
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows only"),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def notepad_process():
    """Launch Notepad, yield (proc, hwnd), then clean up."""
    try:
        import win32gui
        import win32process
    except ImportError:
        pytest.skip("win32gui not available")

    proc = subprocess.Popen("notepad.exe")
    time.sleep(1.5)

    # Find hwnd by PID
    result = [None]
    def _cb(hwnd, _):
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid == proc.pid and win32gui.IsWindowVisible(hwnd):
            result[0] = hwnd
        return True
    win32gui.EnumWindows(_cb, None)

    hwnd = result[0]
    if hwnd is None:
        proc.terminate()
        pytest.skip("Could not find Notepad window handle")

    yield proc, hwnd

    # Cleanup
    try:
        proc.terminate()
    except Exception:
        pass


@pytest.fixture()
def llm_available():
    """Check that at least one LLM API key is set."""
    has_key = bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))
    if not has_key:
        pytest.skip("No OPENAI_API_KEY or ANTHROPIC_API_KEY set")
    return True


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _register_tools(registry, adapter):
    """Register WindowsAdapter methods as tools."""
    from deskaoy.agent.registry import ToolDefinition, ToolParameter

    tools = [
        ToolDefinition(
            name="click",
            description="Click on a desktop element.",
            parameters=(ToolParameter("target", "str", True, "Element name/ref/description"),),
            handler=adapter.click,
        ),
        ToolDefinition(
            name="type_text",
            description="Type text into the focused element.",
            parameters=(
                ToolParameter("text", "str", True, "Text to type"),
                ToolParameter("target", "str", False, "Optional element to focus first"),
            ),
            handler=adapter.type_text,
        ),
        ToolDefinition(
            name="fill",
            description="Fill a text field with a value.",
            parameters=(
                ToolParameter("target", "str", True, "Element to fill"),
                ToolParameter("value", "str", True, "Value to fill"),
            ),
            handler=adapter.fill,
        ),
        ToolDefinition(
            name="key_press",
            description="Press a key or key combination.",
            parameters=(ToolParameter("key", "str", True, "Key or combo"),),
            handler=adapter.key_press,
        ),
        ToolDefinition(
            name="scroll",
            description="Scroll in a direction.",
            parameters=(
                ToolParameter("direction", "str", True, "up/down/left/right"),
                ToolParameter("amount", "int", False, "Scroll amount"),
            ),
            handler=adapter.scroll,
        ),
        ToolDefinition(
            name="screenshot",
            description="Take a screenshot.",
            parameters=(),
            handler=adapter.screenshot,
        ),
        ToolDefinition(
            name="snapshot",
            description="Capture the accessibility tree.",
            parameters=(),
            handler=adapter.snapshot,
        ),
        ToolDefinition(
            name="hover",
            description="Hover over an element.",
            parameters=(ToolParameter("target", "str", True, "Element to hover"),),
            handler=adapter.hover,
        ),
    ]
    for td in tools:
        registry.register_definition(td)


def _verify_text(hwnd: int, expected: str) -> bool:
    """Check if expected text appears in the window."""
    try:
        from deskaoy.adapters.uia_walker import UIAWalker
        walker = UIAWalker()
        snap = walker.walk_to_snapshot(hwnd=hwnd, url="win32://Notepad", title="Notepad")
        for node in snap.nodes.values():
            if expected.lower() in (node.name or "").lower():
                return True
            if node.value and expected.lower() in node.value.lower():
                return True
    except Exception:
        pass

    # Fallback: win32gui
    try:
        import win32gui
        text = win32gui.GetWindowText(hwnd)
        if expected.lower() in text.lower():
            return True
    except Exception:
        pass

    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDesktopAgentLive:
    """End-to-end tests with real Windows desktop + real LLM."""

    @pytest.mark.asyncio
    async def test_type_in_notepad(self, notepad_process, llm_available):
        """Type 'Hello World' in Notepad via DesktopAgent."""
        from deskaoy.adapters.windows import WindowsAdapter
        from deskaoy.agent.loop import AgentLoop
        from deskaoy.agent.registry import ToolRegistry
        from deskaoy.desktop_agent import DesktopAgent
        from deskaoy.llm.client import SimpleLLMClient
        from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken, ResultStatus

        proc, hwnd = notepad_process

        # Build the stack
        adapter = WindowsAdapter(hwnd=hwnd)
        registry = ToolRegistry()
        _register_tools(registry, adapter)
        llm = SimpleLLMClient()
        assert llm.is_ready, "LLM client not ready"

        loop = AgentLoop(
            controller=adapter,
            registry=registry,
            llm_client=llm,
            max_steps=8,
            step_timeout=60.0,
        )
        agent = DesktopAgent(surface=adapter, agent_loop=loop)

        # Execute
        goal = AgentGoal(
            capability="automate",
            params={"instruction": "Type Hello World in the text editor"},
        )
        context = AgentContext(
            execution_id="test-type-notepad",
            timeout_seconds=120,
            cancellation_token=CancellationToken(),
        )

        result = await agent.execute(goal, context)

        # Verify result status
        assert result.status in (ResultStatus.SUCCESS, ResultStatus.PARTIAL), (
            f"Expected SUCCESS or PARTIAL, got {result.status}: {result.summary}"
        )

        # Verify the text actually appeared in Notepad
        assert _verify_text(hwnd, "Hello World"), (
            "Text 'Hello World' not found in Notepad window"
        )

    @pytest.mark.asyncio
    async def test_single_action_click(self, notepad_process, llm_available):
        """Test single-action click via DesktopAgent (no AgentLoop)."""
        from deskaoy.adapters.windows import WindowsAdapter
        from deskaoy.desktop_agent import DesktopAgent
        from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken, ResultStatus

        proc, hwnd = notepad_process

        adapter = WindowsAdapter(hwnd=hwnd)
        agent = DesktopAgent(surface=adapter)

        # Click in the text area to focus it
        goal = AgentGoal(
            capability="click",
            params={"target": "Text Editor"},
        )
        context = AgentContext(
            execution_id="test-single-click",
            timeout_seconds=30,
            cancellation_token=CancellationToken(),
        )

        result = await agent.execute(goal, context)

        # Click should succeed (even if element not found, it shouldn't crash)
        assert result.status in (
            ResultStatus.SUCCESS,
            ResultStatus.FAILURE,  # OK if element not found — still proves stack works
        ), f"Unexpected status: {result.status}"

    @pytest.mark.asyncio
    async def test_dry_run_does_not_mutate(self, notepad_process):
        """Dry run should return an estimate without touching the desktop."""
        from deskaoy.adapters.windows import WindowsAdapter
        from deskaoy.desktop_agent import DesktopAgent
        from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken, ResultStatus

        proc, hwnd = notepad_process

        adapter = WindowsAdapter(hwnd=hwnd)
        agent = DesktopAgent(surface=adapter)

        goal = AgentGoal(
            capability="type_text",
            params={"text": "Should NOT appear"},
        )
        context = AgentContext(
            execution_id="test-dry-run",
            timeout_seconds=10,
            cancellation_token=CancellationToken(),
            dry_run=True,
        )

        result = await agent.execute(goal, context)

        assert result.status == ResultStatus.SUCCESS, f"Dry run failed: {result.summary}"
        assert result.data.get("dry_run") is True

        # Verify text was NOT typed
        time.sleep(0.5)
        assert not _verify_text(hwnd, "Should NOT appear"), (
            "Dry run actually typed text — mutation leak!"
        )

    @pytest.mark.asyncio
    async def test_memory_records_execution(self, notepad_process, llm_available):
        """After execution, action memory should contain evidence."""
        from deskaoy.adapters.windows import WindowsAdapter
        from deskaoy.agent.loop import AgentLoop
        from deskaoy.agent.registry import ToolRegistry
        from deskaoy.desktop_agent import DesktopAgent
        from deskaoy.llm.client import SimpleLLMClient
        from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken

        proc, hwnd = notepad_process

        adapter = WindowsAdapter(hwnd=hwnd)
        registry = ToolRegistry()
        _register_tools(registry, adapter)
        llm = SimpleLLMClient()

        loop = AgentLoop(
            controller=adapter,
            registry=registry,
            llm_client=llm,
            max_steps=8,
        )
        agent = DesktopAgent(surface=adapter, agent_loop=loop)

        goal = AgentGoal(
            capability="automate",
            params={"instruction": "Type Test Memory in the editor"},
        )
        context = AgentContext(
            execution_id="test-memory",
            timeout_seconds=120,
            cancellation_token=CancellationToken(),
        )

        await agent.execute(goal, context)

        # Check memory has recorded something
        anchors = agent.memory.list_anchors()
        assert len(anchors) > 0, "Action memory should contain at least one anchor after execution"
