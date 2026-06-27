"""BATCH-18/TASK-01: Low-level input primitive tests."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from deskaoy.adapters.windows import WindowsAdapter
from deskaoy.cascade.protocol import SurfaceAdapter
from deskaoy.results.types import ErrorCategory


class TestProtocolMethods:
    """Verify SurfaceAdapter has all 5 new abstract methods."""

    def test_has_mouse_down(self):
        """TEST-18-01-01: SurfaceAdapter has mouse_down abstract method."""
        assert hasattr(SurfaceAdapter, "mouse_down")

    def test_has_mouse_up(self):
        """TEST-18-01-02: SurfaceAdapter has mouse_up abstract method."""
        assert hasattr(SurfaceAdapter, "mouse_up")

    def test_has_mouse_drag(self):
        """TEST-18-01-03: SurfaceAdapter has mouse_drag abstract method."""
        assert hasattr(SurfaceAdapter, "mouse_drag")

    def test_has_key_down(self):
        """TEST-18-01-04: SurfaceAdapter has key_down abstract method."""
        assert hasattr(SurfaceAdapter, "key_down")

    def test_has_key_up(self):
        """TEST-18-01-05: SurfaceAdapter has key_up abstract method."""
        assert hasattr(SurfaceAdapter, "key_up")


class TestWindowsAdapterLowLevel:
    """Verify WindowsAdapter implementations."""

    def _make_adapter(self) -> WindowsAdapter:
        adapter = WindowsAdapter(hwnd=1)
        adapter._win32gui = MagicMock()
        adapter._win32gui.IsWindow.return_value = True
        adapter._win32gui.IsIconic.return_value = False
        adapter._win32gui.IsWindowVisible.return_value = True
        adapter._win32gui.GetWindowRect.return_value = (0, 0, 1920, 1080)
        adapter._win32gui.GetDpiForWindow.return_value = 96
        adapter._win32gui.WindowFromPoint.return_value = 1
        adapter._win32gui.SetForegroundWindow = MagicMock()
        adapter._win32api = MagicMock()
        adapter._win32con = MagicMock()
        adapter._pyautogui = MagicMock()
        return adapter

    @pytest.mark.asyncio
    async def test_mouse_down_calls_pyautogui(self):
        """TEST-18-01-06: WindowsAdapter.mouse_down calls pyautogui."""
        adapter = self._make_adapter()
        result = await adapter.mouse_down(button="left")
        assert result.ok is True
        adapter._pyautogui.mouseDown.assert_called_once_with(button="left")

    @pytest.mark.asyncio
    async def test_mouse_up_calls_pyautogui(self):
        """TEST-18-01-07: WindowsAdapter.mouse_up calls pyautogui."""
        adapter = self._make_adapter()
        result = await adapter.mouse_up(button="right")
        assert result.ok is True
        adapter._pyautogui.mouseUp.assert_called_once_with(button="right")

    @pytest.mark.asyncio
    async def test_mouse_drag_calls_pyautogui(self):
        """TEST-18-01-08: WindowsAdapter.mouse_drag moves start->end."""
        adapter = self._make_adapter()
        result = await adapter.mouse_drag("100,200", "300,400")
        assert result.ok is True
        adapter._pyautogui.mouseDown.assert_called_once()
        adapter._pyautogui.mouseUp.assert_called_once()

    @pytest.mark.asyncio
    async def test_key_down_calls_pyautogui(self):
        """TEST-18-01-09: WindowsAdapter.key_down calls pyautogui."""
        adapter = self._make_adapter()
        result = await adapter.key_down("shift")
        assert result.ok is True
        adapter._pyautogui.keyDown.assert_called_once_with("shift")

    @pytest.mark.asyncio
    async def test_key_up_calls_pyautogui(self):
        """TEST-18-01-10: WindowsAdapter.key_up calls pyautogui."""
        adapter = self._make_adapter()
        result = await adapter.key_up("shift")
        assert result.ok is True
        adapter._pyautogui.keyUp.assert_called_once_with("shift")

    @pytest.mark.asyncio
    async def test_key_down_blocks_alt_f4(self):
        """TEST-18-01-11: key_down blocks Alt+F4 via blocklist."""
        adapter = self._make_adapter()
        result = await adapter.key_down("f4", modifiers=1)  # Alt+F4
        assert result.ok is False
        assert result.error.category == ErrorCategory.SECURITY
        adapter._pyautogui.keyDown.assert_not_called()

    @pytest.mark.asyncio
    async def test_mouse_drag_dry_run(self):
        """TEST-18-01-12: mouse_drag dry_run returns without executing."""
        adapter = self._make_adapter()
        result = await adapter.mouse_drag("100,200", "300,400", dry_run=True)
        assert result.ok is True
        assert result.data["dry_run"] is True
        adapter._pyautogui.mouseDown.assert_not_called()

    @pytest.mark.asyncio
    async def test_key_down_dry_run(self):
        """TEST-18-01-13: key_down dry_run returns without executing."""
        adapter = self._make_adapter()
        result = await adapter.key_down("a", dry_run=True)
        assert result.ok is True
        assert result.data["dry_run"] is True
        adapter._pyautogui.keyDown.assert_not_called()
