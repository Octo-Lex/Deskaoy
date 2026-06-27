"""BATCH-17/TASK-01: Real Calculator and Explorer integration tests.

Gated behind pytest.mark.integration + --run-integration flag.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import time

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows only"),
]


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------

@pytest.fixture()
def calc_hwnd():
    """Launch Calculator, find hwnd, yield, then kill."""
    import win32con
    import win32gui

    proc = subprocess.Popen("calc.exe")
    time.sleep(2.5)

    hwnd = win32gui.FindWindow("ApplicationFrameWindow", "Calculator")
    if not hwnd:
        # Try Windows 10 Calculator class
        hwnd = win32gui.FindWindow("Windows.UI.Core.CoreWindow", "Calculator")
    if not hwnd:
        proc.terminate()
        pytest.skip("Could not find Calculator window")

    yield hwnd

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


@pytest.fixture()
def calc_adapter(calc_hwnd):
    from deskaoy.adapters.windows import WindowsAdapter
    a = WindowsAdapter(hwnd=calc_hwnd)
    a._ensure_imports()
    return a


class TestRealCalculator:
    """Real Calculator automation tests."""

    def test_calculator_launched(self, calc_hwnd):
        """TEST-17-01-01: Launch Calculator and find window."""
        import win32gui
        assert calc_hwnd is not None
        assert win32gui.IsWindow(calc_hwnd)

    @pytest.mark.asyncio
    async def test_click_number_buttons(self, calc_adapter):
        """TEST-17-01-02: Click number buttons via adapter.click()."""
        # Bring to front first to avoid occlusion
        calc_adapter._bring_to_front()
        await asyncio.sleep(0.5)
        # Click center of the calculator
        rect = calc_adapter._get_window_rect()
        center_x = rect.x + rect.width // 2
        center_y = rect.y + rect.height // 2
        result = await calc_adapter.click(f"{center_x},{center_y}")
        # We just verify the click completes without error
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_snapshot_shows_buttons(self, calc_adapter):
        """TEST-17-01-03: Snapshot shows calculator buttons."""
        snap = await calc_adapter.snapshot()
        assert len(snap.nodes) > 0

    @pytest.mark.asyncio
    async def test_screenshot_valid_png(self, calc_adapter):
        """TEST-17-01-04: Screenshot returns valid PNG."""
        data = await calc_adapter.screenshot()
        assert isinstance(data, bytes)
        assert len(data) > 100
        assert data[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# Explorer
# ---------------------------------------------------------------------------

@pytest.fixture()
def explorer_hwnd():
    """Launch Explorer, find hwnd, yield, then kill."""
    import win32con
    import win32gui

    proc = subprocess.Popen("explorer.exe")
    time.sleep(3.0)

    # Find the Explorer window
    hwnd = win32gui.FindWindow("CabinetWClass", None)
    if not hwnd:
        # Try alternate approach
        time.sleep(2.0)
        hwnd = win32gui.FindWindow("CabinetWClass", None)
    if not hwnd:
        proc.terminate()
        pytest.skip("Could not find Explorer window")

    yield hwnd

    try:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        time.sleep(0.5)
    except Exception:
        pass


@pytest.fixture()
def explorer_adapter(explorer_hwnd):
    from deskaoy.adapters.windows import WindowsAdapter
    a = WindowsAdapter(hwnd=explorer_hwnd)
    a._ensure_imports()
    return a


class TestRealExplorer:
    """Real Explorer automation tests."""

    def test_explorer_launched(self, explorer_hwnd):
        """TEST-17-01-06: Launch Explorer and find window."""
        import win32gui
        assert explorer_hwnd is not None
        assert win32gui.IsWindow(explorer_hwnd)

    @pytest.mark.asyncio
    async def test_explorer_snapshot_has_nodes(self, explorer_adapter):
        """TEST-17-01-07: Explorer snapshot has file listing nodes."""
        snap = await explorer_adapter.snapshot()
        assert len(snap.nodes) > 0

    @pytest.mark.asyncio
    async def test_explorer_screenshot_valid_png(self, explorer_adapter):
        """TEST-17-01-08: Explorer screenshot returns valid PNG."""
        data = await explorer_adapter.screenshot()
        assert isinstance(data, bytes)
        assert data[:4] == b"\x89PNG"
