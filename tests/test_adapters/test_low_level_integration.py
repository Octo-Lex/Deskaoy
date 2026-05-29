"""BATCH-18/TASK-02: Tool registry wiring + integration tests for low-level input."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import time

import pytest
from unittest.mock import MagicMock

pytestmark_integration = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows only"),
]


class TestToolRegistryWiring:
    """Verify new methods are accessible through tool registry."""

    def test_tool_registry_has_mouse_down(self):
        """TEST-18-02-01: Tool registry exposes mouse_down."""
        from deskaoy.adapters.windows import WindowsAdapter
        adapter = WindowsAdapter(hwnd=1)
        assert hasattr(adapter, "mouse_down")
        assert callable(adapter.mouse_down)

    def test_tool_registry_has_key_down(self):
        """TEST-18-02-02: Tool registry exposes key_down."""
        from deskaoy.adapters.windows import WindowsAdapter
        adapter = WindowsAdapter(hwnd=1)
        assert hasattr(adapter, "key_down")
        assert callable(adapter.key_down)


# ---------------------------------------------------------------------------
# Integration tests (gated behind --run-integration)
# ---------------------------------------------------------------------------

@pytest.fixture()
def notepad_for_lowlevel():
    """Launch Notepad for low-level input testing."""
    import win32gui
    import win32con

    proc = subprocess.Popen(["notepad.exe"])
    time.sleep(2.0)

    hwnd = win32gui.FindWindow("Notepad", None)
    if not hwnd:
        proc.terminate()
        pytest.skip("Could not find Notepad")

    from deskaoy.adapters.windows import WindowsAdapter
    adapter = WindowsAdapter(hwnd=hwnd)
    adapter._ensure_imports()

    yield adapter

    try:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        time.sleep(0.5)
    except Exception:
        pass
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


@pytest.mark.integration
@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
class TestRealLowLevelInput:
    """Real desktop tests for low-level input primitives."""

    @pytest.mark.asyncio
    async def test_real_mouse_down_up(self, notepad_for_lowlevel):
        """TEST-18-02-03: Real mouse_down/up cycle on Notepad."""
        adapter = notepad_for_lowlevel
        result_down = await adapter.mouse_down(button="left")
        assert result_down.ok is True
        await asyncio.sleep(0.1)
        result_up = await adapter.mouse_up(button="left")
        assert result_up.ok is True

    @pytest.mark.asyncio
    async def test_real_key_down_up(self, notepad_for_lowlevel):
        """TEST-18-02-04: Real key_down/up cycle on Notepad."""
        adapter = notepad_for_lowlevel
        result_down = await adapter.key_down("a")
        assert result_down.ok is True
        await asyncio.sleep(0.1)
        result_up = await adapter.key_up("a")
        assert result_up.ok is True
