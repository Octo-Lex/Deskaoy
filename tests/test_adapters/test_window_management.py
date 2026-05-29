"""BATCH-20: Window & display management tests."""
from __future__ import annotations

import asyncio
import sys

import pytest
from unittest.mock import MagicMock

from deskaoy.adapters.windows import WindowsAdapter
from deskaoy.cascade.protocol import SurfaceAdapter

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows-specific window management tests",
)


def _make_adapter() -> WindowsAdapter:
    adapter = WindowsAdapter(hwnd=1)
    adapter._win32gui = MagicMock()
    adapter._win32gui.IsWindow.return_value = True
    adapter._win32gui.IsIconic.return_value = False
    adapter._win32gui.IsWindowVisible.return_value = True
    adapter._win32gui.GetWindowRect.return_value = (0, 0, 1920, 1080)
    adapter._win32gui.GetDpiForWindow.return_value = 96
    adapter._win32gui.WindowFromPoint.return_value = 1
    adapter._win32gui.SetForegroundWindow = MagicMock()
    adapter._win32gui.SetWindowPos = MagicMock()
    adapter._win32api = MagicMock()
    adapter._win32con = MagicMock()
    adapter._pyautogui = MagicMock()
    return adapter


class TestListDisplays:
    @pytest.mark.asyncio
    async def test_list_displays_returns_list(self):
        adapter = _make_adapter()
        displays = await adapter.list_displays()
        assert isinstance(displays, list)

    @pytest.mark.asyncio
    async def test_list_displays_has_keys(self):
        adapter = _make_adapter()
        displays = await adapter.list_displays()
        if displays:
            assert "width" in displays[0]
            assert "height" in displays[0]


class TestListWindows:
    @pytest.mark.asyncio
    async def test_list_windows_returns_list(self):
        adapter = _make_adapter()
        # Mock EnumWindows to call callback with test windows
        def mock_enum(cb, extra):
            cb(100, None)
            return True
        adapter._win32gui.EnumWindows = mock_enum
        adapter._win32gui.GetWindowText = lambda hwnd: "Test Window" if hwnd == 100 else ""
        windows = await adapter.list_windows()
        assert isinstance(windows, list)


class TestSetWindowBounds:
    @pytest.mark.asyncio
    async def test_set_window_bounds(self):
        adapter = _make_adapter()
        result = await adapter.set_window_bounds(100, 200, 800, 600)
        assert result.ok is True
        adapter._win32gui.SetWindowPos.assert_called_once()


class TestFocusWindow:
    @pytest.mark.asyncio
    async def test_focus_by_title(self):
        adapter = _make_adapter()
        adapter._win32gui.FindWindow.return_value = 12345
        result = await adapter.focus_window({"title": "Calculator"})
        assert result.ok is True
        adapter._win32gui.SetForegroundWindow.assert_called_with(12345)

    @pytest.mark.asyncio
    async def test_focus_not_found(self):
        adapter = _make_adapter()
        adapter._win32gui.FindWindow.return_value = 0
        result = await adapter.focus_window({"title": "Nonexistent"})
        assert result.ok is False

    @pytest.mark.asyncio
    async def test_focus_no_query(self):
        adapter = _make_adapter()
        result = await adapter.focus_window({})
        assert result.ok is False


class _Stub(SurfaceAdapter):
    async def click(self, t, **kw): return NotImplemented
    async def fill(self, t, v, **kw): return NotImplemented
    async def type_text(self, t, **kw): return NotImplemented
    async def key_press(self, k, m=0, **kw): return NotImplemented
    async def scroll(self, d, a=500, **kw): return NotImplemented
    async def screenshot(self): return b""
    async def snapshot(self): from deskaoy.cascade.types import AXSnapshot; return AXSnapshot(url="", title="", nodes={})
    async def evaluate(self, e): return None
    def current_url(self): return ""
    async def current_title(self): return ""


class TestProtocolDefaults:
    @pytest.mark.asyncio
    async def test_default_list_displays(self):
        result = await _Stub().list_displays()
        assert result == []

    @pytest.mark.asyncio
    async def test_default_set_window_bounds(self):
        result = await _Stub().set_window_bounds(0, 0, 800, 600)
        assert result.ok is False
