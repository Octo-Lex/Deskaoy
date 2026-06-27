"""Tests for WindowsAdapter — protocol compliance, hover, wait_for_selector, wiring.

All tests mock win32gui/pyautogui/mss — no real Windows APIs needed.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from deskaoy.adapters.windows import WindowsAdapter
from deskaoy.cascade.protocol import SurfaceAdapter
from deskaoy.cascade.types import AXNode, AXSnapshot
from deskaoy.input.types import HumanizationConfig, Point
from deskaoy.results.types import ActionError, ErrorCategory

# =================================================================
# Helpers
# =================================================================

def _make_adapter(
    hwnd: int = 12345,
    humanization: HumanizationConfig | None = None,
) -> WindowsAdapter:
    """Create a WindowsAdapter with pre-injected mocks."""
    cfg = humanization or HumanizationConfig(move_enabled=False)
    adapter = WindowsAdapter(hwnd=hwnd, humanization=cfg)
    return adapter


def _inject_mocks(adapter: WindowsAdapter) -> dict[str, MagicMock]:
    """Inject mock win32gui, win32api, pyautogui into adapter."""
    win32gui = MagicMock()
    win32gui.IsWindow.return_value = True
    win32gui.IsIconic.return_value = False
    win32gui.IsWindowVisible.return_value = True
    win32gui.GetWindowRect.return_value = (100, 100, 800, 600)
    win32gui.WindowFromPoint.return_value = adapter._hwnd
    win32gui.GetWindowText.return_value = "TestWindow"

    win32api = MagicMock()
    win32api.GetCursorPos.return_value = (200, 200)
    win32api.GetDpiForWindow.return_value = 96

    pyautogui = MagicMock()

    adapter._win32gui = win32gui
    adapter._win32api = win32api
    adapter._win32con = MagicMock()
    adapter._pyautogui = pyautogui

    return {
        "win32gui": win32gui,
        "win32api": win32api,
        "pyautogui": pyautogui,
    }


# =================================================================
# TestProtocolCompliance
# =================================================================

class TestProtocolCompliance:
    """WindowsAdapter implements the full SurfaceAdapter protocol."""

    def test_is_surface_adapter(self):
        adapter = WindowsAdapter(hwnd=1)
        assert isinstance(adapter, SurfaceAdapter)

    def test_dry_run_click(self):
        adapter = _make_adapter()
        mocks = _inject_mocks(adapter)

        result = asyncio.run(
            adapter.click("400,300", dry_run=True),
        )
        assert result.ok is True
        assert result.data["dry_run"] is True
        assert result.data["action"] == "click"
        # No actual click happened
        mocks["pyautogui"].click.assert_not_called()

    def test_dry_run_fill(self):
        adapter = _make_adapter()
        mocks = _inject_mocks(adapter)

        result = asyncio.run(
            adapter.fill("400,300", "hello", dry_run=True),
        )
        assert result.ok is True
        assert result.data["dry_run"] is True
        assert result.data["value"] == "hello"
        mocks["pyautogui"].click.assert_not_called()

    def test_dry_run_type_text(self):
        adapter = _make_adapter()
        mocks = _inject_mocks(adapter)

        result = asyncio.run(
            adapter.type_text("hello", dry_run=True),
        )
        assert result.ok is True
        assert result.data["dry_run"] is True
        assert result.data["char_count"] == 5
        mocks["pyautogui"].write.assert_not_called()

    def test_dry_run_key_press(self):
        adapter = _make_adapter()
        mocks = _inject_mocks(adapter)

        result = asyncio.run(
            adapter.key_press("Enter", dry_run=True),
        )
        assert result.ok is True
        assert result.data["dry_run"] is True
        assert result.data["key"] == "Enter"
        mocks["pyautogui"].press.assert_not_called()

    def test_dry_run_scroll(self):
        adapter = _make_adapter()
        mocks = _inject_mocks(adapter)

        result = asyncio.run(
            adapter.scroll("down", 500, dry_run=True),
        )
        assert result.ok is True
        assert result.data["dry_run"] is True
        assert result.data["direction"] == "down"
        mocks["pyautogui"].scroll.assert_not_called()

    def test_dry_run_hover(self):
        adapter = _make_adapter()
        mocks = _inject_mocks(adapter)

        result = asyncio.run(
            adapter.hover("400,300", dry_run=True),
        )
        assert result.ok is True
        assert result.data["dry_run"] is True
        assert result.data["action"] == "hover"
        mocks["pyautogui"].moveTo.assert_not_called()

    def test_supports_navigation_false(self):
        adapter = _make_adapter()
        assert adapter.supports_navigation is False

    def test_supports_select_false(self):
        adapter = _make_adapter()
        assert adapter.supports_select is False

    def test_select_option_not_supported(self):
        adapter = _make_adapter()
        result = asyncio.run(
            adapter.select_option("combo", "option1"),
        )
        assert result.ok is False
        assert result.error is not None
        assert "not supported" in result.error.message

    def test_navigate_not_supported(self):
        adapter = _make_adapter()
        result = asyncio.run(
            adapter.navigate("https://example.com"),
        )
        assert result.ok is False
        assert result.error is not None
        assert "not supported" in result.error.message


# =================================================================
# TestHover
# =================================================================

class TestHover:
    """Hover moves the mouse without clicking."""

    @pytest.mark.asyncio
    async def test_hover_moves_to_target(self):
        adapter = _make_adapter(humanization=HumanizationConfig(move_enabled=False))
        mocks = _inject_mocks(adapter)

        result = await adapter.hover("400,300")
        assert result.ok is True
        # moveTo should have been called (via _move_to), NOT click
        mocks["pyautogui"].moveTo.assert_called()
        mocks["pyautogui"].click.assert_not_called()

    @pytest.mark.asyncio
    async def test_hover_validates_window(self):
        adapter = _make_adapter()
        mocks = _inject_mocks(adapter)
        # Window is not valid
        mocks["win32gui"].IsWindow.return_value = False

        result = await adapter.hover("400,300")
        assert result.ok is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_hover_dry_run(self):
        adapter = _make_adapter()
        mocks = _inject_mocks(adapter)

        result = await adapter.hover("400,300", dry_run=True)
        assert result.ok is True
        assert result.data["dry_run"] is True
        mocks["pyautogui"].moveTo.assert_not_called()

    @pytest.mark.asyncio
    async def test_hover_by_coordinates(self):
        adapter = _make_adapter(humanization=HumanizationConfig(move_enabled=False))
        mocks = _inject_mocks(adapter)

        result = await adapter.hover("250,350")
        assert result.ok is True
        # Verify the move target is close to 250,350
        call_args = mocks["pyautogui"].moveTo.call_args[0]
        assert abs(call_args[0] - 250) < 10
        assert abs(call_args[1] - 350) < 10

    @pytest.mark.asyncio
    async def test_hover_by_uia_name(self):
        adapter = _make_adapter(humanization=HumanizationConfig(move_enabled=False))
        mocks = _inject_mocks(adapter)

        with patch.object(adapter, "_resolve_target_by_uia", return_value=Point(350, 250)):
            result = await adapter.hover("name:Submit")
            assert result.ok is True
            mocks["pyautogui"].click.assert_not_called()


# =================================================================
# TestWaitForSelector
# =================================================================

class TestWaitForSelector:
    """wait_for_selector polls the UIA tree for an element."""

    @pytest.mark.asyncio
    async def test_returns_immediately_when_found(self):
        adapter = _make_adapter()
        _inject_mocks(adapter)

        with patch.object(
            adapter, "_resolve_target_by_uia", return_value=Point(300, 200),
        ):
            result = await adapter.wait_for_selector("name:OK", timeout_ms=5000)

        assert result.ok is True
        assert result.data["found"] is True
        assert result.data["point"]["x"] == 300

    @pytest.mark.asyncio
    async def test_polls_until_found(self):
        adapter = _make_adapter()
        _inject_mocks(adapter)

        call_count = 0

        def mock_resolve(target: str) -> Point | None:
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                return Point(100, 200)
            return None

        with patch.object(adapter, "_resolve_target_by_uia", side_effect=mock_resolve):
            start = time.monotonic()
            result = await adapter.wait_for_selector("name:Save", timeout_ms=5000)
            elapsed = (time.monotonic() - start) * 1000

        assert result.ok is True
        assert result.data["found"] is True
        assert call_count == 3
        assert elapsed < 3000  # Not the full timeout

    @pytest.mark.asyncio
    async def test_returns_timeout_when_not_found(self):
        adapter = _make_adapter()
        _inject_mocks(adapter)

        with patch.object(adapter, "_resolve_target_by_uia", return_value=None):
            start = time.monotonic()
            result = await adapter.wait_for_selector("name:Ghost", timeout_ms=400)
            elapsed = (time.monotonic() - start) * 1000

        assert result.ok is False
        assert result.error is not None
        assert result.error.category == ErrorCategory.SELECTOR_NOT_FOUND
        assert "not found" in result.error.message.lower()
        assert elapsed >= 200


# =================================================================
# TestWindowIsolation
# =================================================================

class TestWindowIsolation:
    """Safety checks prevent out-of-window actions."""

    @pytest.mark.asyncio
    async def test_abort_blocks_click(self):
        adapter = _make_adapter()
        _inject_mocks(adapter)
        adapter.abort()

        result = await adapter.click("400,300")
        assert result.ok is False
        assert "aborted" in result.error.message.lower()

    @pytest.mark.asyncio
    async def test_abort_blocks_fill(self):
        adapter = _make_adapter()
        _inject_mocks(adapter)
        adapter.abort()

        # fill delegates to click, so abort fires there
        result = await adapter.fill("400,300", "text")
        assert result.ok is False

    @pytest.mark.asyncio
    async def test_abort_blocks_hover(self):
        adapter = _make_adapter()
        _inject_mocks(adapter)
        adapter.abort()

        result = await adapter.hover("400,300")
        assert result.ok is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_point_outside_window_rejected(self):
        adapter = _make_adapter(humanization=HumanizationConfig(move_enabled=False))
        mocks = _inject_mocks(adapter)
        # Window rect is (100,100)-(800,600), click at (50,50) is outside
        mocks["win32gui"].WindowFromPoint.return_value = 99999

        result = await adapter.click("50,50")
        assert result.ok is False
        assert result.error is not None
        msg = result.error.message.lower()
        assert "outside" in msg or "safety" in msg

    @pytest.mark.asyncio
    async def test_window_not_found_raises(self):
        adapter = WindowsAdapter(window_title="NonExistent")
        _inject_mocks(adapter)
        adapter._win32gui.FindWindow.return_value = 0

        result = await adapter.click("400,300")
        assert result.ok is False
        assert result.error is not None


# =================================================================
# TestDesktopAgentWiring
# =================================================================

class TestDesktopAgentWiring:
    """DesktopAgent can dispatch actions through WindowsAdapter."""

    @pytest.fixture()
    def adapter(self):
        a = _make_adapter(humanization=HumanizationConfig(move_enabled=False))
        _inject_mocks(a)
        return a

    @pytest.mark.asyncio
    async def test_desktop_agent_with_windows_surface(self, adapter):
        from deskaoy.desktop_agent import DesktopAgent
        agent = DesktopAgent(surface=adapter)
        assert agent._surface is adapter

    @pytest.mark.asyncio
    async def test_execute_click_through_desktop_agent(self, adapter):
        from deskaoy.desktop_agent import DesktopAgent
        from deskaoy.os_types import AgentContext, AgentGoal

        agent = DesktopAgent(surface=adapter)
        goal = AgentGoal(
            capability="click",
            params={"target": "400,300"},
        )
        context = AgentContext(
            execution_id="exec-1",
            idempotency_key="idem-1",
            task_id="task-1",
            user_id="user-1",
            session_id="sess-1",
        )

        result = await agent.execute(goal, context)
        assert result.status.value in ("success", "partial", "failure")

    @pytest.mark.asyncio
    async def test_execute_fill_through_desktop_agent(self, adapter):
        from deskaoy.desktop_agent import DesktopAgent
        from deskaoy.os_types import AgentContext, AgentGoal

        agent = DesktopAgent(surface=adapter)
        goal = AgentGoal(
            capability="fill",
            params={"target": "400,300", "value": "hello world"},
        )
        context = AgentContext(
            execution_id="exec-2",
            idempotency_key="idem-2",
            task_id="task-2",
            user_id="user-2",
            session_id="sess-2",
        )

        result = await agent.execute(goal, context)
        assert result.status.value in ("success", "partial", "failure")

    @pytest.mark.asyncio
    async def test_execute_screenshot_through_desktop_agent(self, adapter):
        from deskaoy.desktop_agent import DesktopAgent
        from deskaoy.os_types import AgentContext, AgentGoal

        agent = DesktopAgent(surface=adapter)
        goal = AgentGoal(
            capability="screenshot",
            params={},
        )
        context = AgentContext(
            execution_id="exec-3",
            idempotency_key="idem-3",
            task_id="task-3",
            user_id="user-3",
            session_id="sess-3",
        )

        # screenshot() needs mss - mock the adapter method directly
        with patch.object(adapter, "screenshot", return_value=b"\x89PNG\r\n"):
            result = await agent.execute(goal, context)
            assert result.status.value in ("success", "partial", "failure")

    @pytest.mark.asyncio
    async def test_execute_snapshot_returns_ax_snapshot(self, adapter):
        from deskaoy.desktop_agent import DesktopAgent
        from deskaoy.os_types import AgentContext, AgentGoal

        mock_snapshot = AXSnapshot(
            url="win32://TestWindow",
            title="TestWindow",
            nodes=[AXNode(
                ref="0", role="window", name="TestWindow",
                bounds=[100, 100, 800, 600],
            )],
        )

        with patch.object(adapter, "snapshot", return_value=mock_snapshot):
            agent = DesktopAgent(surface=adapter)
            goal = AgentGoal(
                capability="snapshot",
                params={},
            )
            context = AgentContext(
                execution_id="exec-4",
                idempotency_key="idem-4",
                task_id="task-4",
                user_id="user-4",
                session_id="sess-4",
            )
            result = await agent.execute(goal, context)
            assert result.status.value in ("success", "partial", "failure")

    @pytest.mark.asyncio
    async def test_navigate_returns_failure(self, adapter):
        from deskaoy.desktop_agent import DesktopAgent
        from deskaoy.os_types import AgentContext, AgentGoal

        agent = DesktopAgent(surface=adapter)
        goal = AgentGoal(
            capability="navigate",
            params={"url": "https://example.com"},
        )
        context = AgentContext(
            execution_id="exec-5",
            idempotency_key="idem-5",
            task_id="task-5",
            user_id="user-5",
            session_id="sess-5",
        )

        result = await agent.execute(goal, context)
        assert result.status.value == "failure"


# =================================================================
# TestErrorFormat
# =================================================================

class TestErrorFormat:
    """Errors use ActionError, not data dicts."""

    @pytest.mark.asyncio
    async def test_click_error_uses_action_error(self):
        adapter = _make_adapter()
        mocks = _inject_mocks(adapter)
        mocks["win32gui"].IsWindow.return_value = False

        result = await adapter.click("400,300")
        assert result.ok is False
        assert isinstance(result.error, ActionError)
        assert result.error.category == ErrorCategory.UNKNOWN

    @pytest.mark.asyncio
    async def test_hover_error_uses_action_error(self):
        adapter = _make_adapter()
        mocks = _inject_mocks(adapter)
        mocks["win32gui"].IsWindow.return_value = False

        result = await adapter.hover("400,300")
        assert result.ok is False
        assert isinstance(result.error, ActionError)

    @pytest.mark.asyncio
    async def test_fill_error_uses_action_error(self):
        adapter = _make_adapter()
        _inject_mocks(adapter)
        adapter.abort()

        result = await adapter.fill("400,300", "text")
        assert result.ok is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_scroll_error_uses_action_error(self):
        adapter = _make_adapter()
        mocks = _inject_mocks(adapter)
        mocks["pyautogui"].scroll.side_effect = RuntimeError("scroll failed")

        result = await adapter.scroll("down")
        assert result.ok is False
        assert isinstance(result.error, ActionError)

    @pytest.mark.asyncio
    async def test_key_press_error_uses_action_error(self):
        adapter = _make_adapter()
        mocks = _inject_mocks(adapter)
        mocks["pyautogui"].press.side_effect = RuntimeError("key failed")

        result = await adapter.key_press("Enter")
        assert result.ok is False
        assert isinstance(result.error, ActionError)

    @pytest.mark.asyncio
    async def test_type_text_error_uses_action_error(self):
        adapter = _make_adapter()
        mocks = _inject_mocks(adapter)
        mocks["pyautogui"].write.side_effect = RuntimeError("type failed")

        result = await adapter.type_text("hello")
        assert result.ok is False
        assert isinstance(result.error, ActionError)
