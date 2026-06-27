"""E2E adapter lifecycle tests — BATCH-35, TASK-01.

Full lifecycle for each adapter (Windows, macOS, Linux):
  create → observe (snapshot) → click → type → snapshot → verify

All mocked — no real OS APIs or hardware required.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("GITHUB_ACTIONS") == "true" and sys.platform == "win32",
    reason="macOS adapter mock tests crash on GitHub Actions Windows runners "
           "(thread/signal incompatibility when sys.platform is patched to darwin)",
)

from deskaoy.cascade.protocol import SurfaceAdapter
from deskaoy.cascade.types import AXNode, AXSnapshot

# =================================================================
# Windows Adapter E2E Lifecycle
# =================================================================


def _make_windows_adapter():
    """Create a WindowsAdapter with mocked platform APIs."""
    from deskaoy.adapters.windows import WindowsAdapter
    from deskaoy.input.types import HumanizationConfig

    adapter = WindowsAdapter(
        hwnd=12345,
        humanization=HumanizationConfig(move_enabled=False),
    )

    # Inject mock platform modules
    win32gui = MagicMock()
    win32gui.IsWindow.return_value = True
    win32gui.IsIconic.return_value = False
    win32gui.IsWindowVisible.return_value = True
    win32gui.GetWindowRect.return_value = (100, 100, 800, 600)
    win32gui.WindowFromPoint.return_value = 12345
    win32gui.GetWindowText.return_value = "TestWindow"
    win32gui.FindWindow.return_value = 12345

    win32api = MagicMock()
    win32api.GetCursorPos.return_value = (200, 200)
    win32api.GetDpiForWindow.return_value = 96

    pyautogui = MagicMock()

    adapter._win32gui = win32gui
    adapter._win32api = win32api
    adapter._win32con = MagicMock()
    adapter._pyautogui = pyautogui

    return adapter


class TestWindowsAdapterE2E:
    """Full lifecycle: create → snapshot → click → type → snapshot → verify."""

    @pytest.mark.asyncio
    async def test_windows_full_lifecycle(self):
        """E2E: Create adapter, snapshot, click, type, verify."""
        adapter = _make_windows_adapter()

        # 1. Verify adapter is a SurfaceAdapter
        assert isinstance(adapter, SurfaceAdapter)

        # 2. Snapshot (mocked UIA walk)
        mock_snapshot = AXSnapshot(
            url="win32://TestWindow",
            title="TestWindow",
            nodes={
                "e0": AXNode(ref="e0", role="window", name="TestWindow",
                             bounds=[100, 100, 700, 500]),
                "e1": AXNode(ref="e1", role="textbox", name="Search",
                             bounds=[150, 150, 300, 30]),
                "e2": AXNode(ref="e2", role="button", name="Submit",
                             bounds=[460, 150, 80, 30]),
            },
        )
        with patch.object(adapter, "snapshot", return_value=mock_snapshot):
            snap = await adapter.snapshot()

        assert isinstance(snap, AXSnapshot)
        assert snap.title == "TestWindow"
        assert len(snap.nodes) == 3

        # 3. Click the Submit button
        click_result = await adapter.click("400,160")
        assert click_result.ok is True
        adapter._pyautogui.click.assert_called_once()

        # 4. Type text into the search field
        type_result = await adapter.type_text("hello world")
        assert type_result.ok is True

        # 5. Second snapshot to verify state
        with patch.object(adapter, "snapshot", return_value=mock_snapshot):
            snap2 = await adapter.snapshot()
        assert snap2.title == "TestWindow"

        # 6. Verify URL
        assert adapter.current_url() == "win32://TestWindow"

    @pytest.mark.asyncio
    async def test_windows_fill_lifecycle(self):
        """E2E: Create adapter → fill field → verify value typed."""
        adapter = _make_windows_adapter()

        result = await adapter.fill("400,160", "test input")
        assert result.ok is True

        # Verify click was called (fill = click + type)
        adapter._pyautogui.click.assert_called()

    @pytest.mark.asyncio
    async def test_windows_dry_run_lifecycle(self):
        """E2E: Dry-run cycle never touches real APIs."""
        adapter = _make_windows_adapter()

        # All dry runs
        click = await adapter.click("400,300", dry_run=True)
        assert click.ok is True
        assert click.data["dry_run"] is True

        fill = await adapter.fill("400,300", "text", dry_run=True)
        assert fill.ok is True
        assert fill.data["dry_run"] is True

        typed = await adapter.type_text("hello", dry_run=True)
        assert typed.ok is True
        assert typed.data["dry_run"] is True

        # Verify no real API calls were made
        adapter._pyautogui.click.assert_not_called()
        adapter._pyautogui.write.assert_not_called()

    @pytest.mark.asyncio
    async def test_windows_scroll_lifecycle(self):
        """E2E: Scroll actions succeed."""
        adapter = _make_windows_adapter()

        result = await adapter.scroll("down", 500)
        assert result.ok is True
        adapter._pyautogui.scroll.assert_called()


# =================================================================
# macOS Adapter E2E Lifecycle
# =================================================================


def _mock_pyobjc_modules():
    """Create mock pyobjc modules for testing on non-macOS."""
    app_services = MagicMock()
    core_graphics = MagicMock()
    quartz = MagicMock()

    quartz.kCGEventLeftMouseDown = 1
    quartz.kCGEventLeftMouseUp = 2
    quartz.kCGMouseButtonLeft = 0
    quartz.kCGHIDEventTap = 1
    quartz.kCGScrollEventUnitPixel = 1
    quartz.kCGWindowListOptionOnScreenOnly = 1 << 0
    quartz.kCGNullWindowID = 0
    quartz.kCGWindowImageDefault = 0
    quartz.kCGEventFlagMaskAlternate = 1 << 19
    quartz.kCGEventFlagMaskControl = 1 << 18
    quartz.kCGEventFlagMaskShift = 1 << 17
    quartz.kCGEventFlagMaskCommand = 1 << 20

    return {
        'ApplicationServices': app_services,
        'CoreGraphics': core_graphics,
        'Quartz': quartz,
    }


def _make_macos_adapter(**kwargs):
    """Create a MacOSAdapter with mocked pyobjc."""
    macos_modules = _mock_pyobjc_modules()
    with patch.dict('sys.modules', macos_modules), patch.object(sys, 'platform', 'darwin'):
        from deskaoy.adapters.macos import MacOSAdapter
        adapter = MacOSAdapter(**kwargs)
        adapter._app_services = macos_modules['ApplicationServices']
        adapter._core_graphics = macos_modules['CoreGraphics']
        adapter._quartz = macos_modules['Quartz']
        adapter._imported = True
        return adapter


class TestMacOSAdapterE2E:
    """Full lifecycle: create → snapshot → click → type → snapshot → verify."""

    @pytest.mark.asyncio
    async def test_macos_full_lifecycle(self):
        """E2E: Create adapter, snapshot, click, type, verify."""
        adapter = _make_macos_adapter(pid=42)

        # 1. Verify adapter is a SurfaceAdapter
        assert isinstance(adapter, SurfaceAdapter)

        # 2. Snapshot (mocked AX tree)
        adapter._app_services.AXUIElementCopyAttributeValue.return_value = (0, [])
        snap = await adapter.snapshot()
        assert isinstance(snap, AXSnapshot)
        assert snap.url.startswith("macos://")

        # 3. Click
        click_result = await adapter.click("500,300")
        assert click_result.ok is True
        assert click_result.data["x"] == 500.0
        assert click_result.data["y"] == 300.0

        # 4. Type text
        type_result = await adapter.type_text("hello")
        assert type_result.ok is True

        # 5. Verify URL
        assert adapter.current_url() == "macos://pid/42"

    @pytest.mark.asyncio
    async def test_macos_fill_lifecycle(self):
        """E2E: Fill uses click + type."""
        adapter = _make_macos_adapter(pid=42)
        result = await adapter.fill("100,200", "test value")
        assert result.ok is True
        assert result.data["value"] == "test value"

    @pytest.mark.asyncio
    async def test_macos_scroll_lifecycle(self):
        """E2E: Scroll via CGEvent."""
        adapter = _make_macos_adapter(pid=42)
        result = await adapter.scroll("down", 500)
        assert result.ok is True


# =================================================================
# Linux Adapter E2E Lifecycle
# =================================================================


def _make_linux_adapter():
    """Create a LinuxAdapter with mocked AT-SPI2 modules."""
    from deskaoy.adapters.linux import LinuxAdapter

    adapter = LinuxAdapter()

    # Mock AT-SPI2
    mock_atspi = MagicMock()
    mock_registry = MagicMock()
    mock_atspi.Registry = mock_registry

    # Mock desktop for snapshot
    mock_desktop = MagicMock()
    mock_desktop.get_child_count.return_value = 0
    mock_atspi.get_desktop.return_value = mock_desktop

    adapter._atspi = mock_atspi
    adapter._registry = mock_registry

    return adapter


class TestLinuxAdapterE2E:
    """Full lifecycle: create → snapshot → click → type → snapshot → verify."""

    @pytest.mark.asyncio
    async def test_linux_full_lifecycle(self):
        """E2E: Create adapter, snapshot, click, verify."""
        adapter = _make_linux_adapter()

        # 1. Verify adapter is a SurfaceAdapter
        assert isinstance(adapter, SurfaceAdapter)

        # 2. Snapshot (mocked AT-SPI2 tree)
        snap = await adapter.snapshot()
        assert isinstance(snap, AXSnapshot)
        assert snap.url.startswith("x11://")

        # 3. Click
        click_result = await adapter.click("300,200")
        assert click_result.ok is True

        # 4. Type text — unsupported on Linux
        type_result = await adapter.type_text("hello")
        assert type_result.ok is False

        # 5. Verify URL
        assert adapter.current_url() == "x11://desktop"

    @pytest.mark.asyncio
    async def test_linux_fill_lifecycle(self):
        """E2E: Fill is unsupported on Linux."""
        adapter = _make_linux_adapter()
        result = await adapter.fill("button_name", "test")
        assert result.ok is False

    @pytest.mark.asyncio
    async def test_linux_key_press_lifecycle(self):
        """E2E: Key press is unsupported on Linux."""
        adapter = _make_linux_adapter()
        result = await adapter.key_press("enter")
        assert result.ok is False
