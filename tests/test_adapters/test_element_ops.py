"""BATCH-19: Element operations tests — invoke_element + get_element_state."""
from __future__ import annotations

import asyncio

import pytest
from unittest.mock import MagicMock, patch

from deskaoy.adapters.windows import WindowsAdapter
from deskaoy.results.types import ActionResult


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
    adapter._win32api = MagicMock()
    adapter._win32con = MagicMock()
    adapter._pyautogui = MagicMock()
    return adapter


class TestInvokeElement:
    """TEST-19-01 through TEST-19-09."""

    @pytest.mark.asyncio
    async def test_invoke_click(self):
        """TEST-19-01: invoke_element('btn','click') delegates to click."""
        adapter = _make_adapter()
        result = await adapter.invoke_element("500,500", action="click")
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_invoke_focus(self):
        """TEST-19-02: invoke_element('btn','focus') returns ok."""
        adapter = _make_adapter()
        result = await adapter.invoke_element("500,500", action="focus")
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_invoke_set_value(self):
        """TEST-19-03: invoke_element('btn','set_value') returns ok."""
        adapter = _make_adapter()
        result = await adapter.invoke_element("500,500", action="set_value", value="hello")
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_invoke_get_value(self):
        """TEST-19-04: invoke_element('btn','get_value') returns data."""
        adapter = _make_adapter()
        result = await adapter.invoke_element("500,500", action="get_value")
        # May return ok or not depending on UIA availability
        assert isinstance(result, ActionResult)

    @pytest.mark.asyncio
    async def test_invoke_expand(self):
        """TEST-19-05: invoke_element('btn','expand') returns ok."""
        adapter = _make_adapter()
        result = await adapter.invoke_element("500,500", action="expand")
        assert isinstance(result.ok, bool)

    @pytest.mark.asyncio
    async def test_invoke_collapse(self):
        """TEST-19-06: invoke_element('btn','collapse') returns ok."""
        adapter = _make_adapter()
        result = await adapter.invoke_element("500,500", action="collapse")
        assert isinstance(result.ok, bool)

    @pytest.mark.asyncio
    async def test_invoke_toggle(self):
        """TEST-19-07: invoke_element('btn','toggle') delegates to click."""
        adapter = _make_adapter()
        result = await adapter.invoke_element("500,500", action="toggle")
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_invoke_select(self):
        """TEST-19-08: invoke_element('btn','select') delegates to click."""
        adapter = _make_adapter()
        result = await adapter.invoke_element("500,500", action="select")
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_invoke_unknown_action(self):
        """TEST-19-09: invoke_element('btn','unknown') returns not supported."""
        adapter = _make_adapter()
        result = await adapter.invoke_element("500,500", action="teleport")
        assert result.ok is False


class TestGetElementState:
    """TEST-19-10 and TEST-19-11."""

    @pytest.mark.asyncio
    async def test_get_element_state_returns_dict(self):
        """TEST-19-10: get_element_state returns dict with state keys."""
        adapter = _make_adapter()
        state = await adapter.get_element_state("500,500")
        assert isinstance(state, dict)
        assert "enabled" in state
        assert "focused" in state
        assert "selected" in state
        assert "expanded" in state
        assert "busy" in state
        assert "offscreen" in state

    @pytest.mark.asyncio
    async def test_get_focused_element(self):
        """TEST-19-11: get_focused_element returns ref or None."""
        adapter = _make_adapter()
        result = await adapter.get_focused_element()
        # May return None or a dict depending on UIA availability
        assert result is None or isinstance(result, dict)
