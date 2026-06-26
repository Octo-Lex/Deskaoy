"""Tests for MacOSAdapter — TASK-01 (BATCH-33).

All tests mock pyobjc modules — no macOS hardware required (HB-01).
Uses the mock pattern from BATCH-33-BLUEPRINT:
  patch.dict('sys.modules', macos_modules) to fake pyobjc.
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# These tests mock pyobjc and patch sys.platform to 'darwin'. On GitHub Actions
# Windows runners this causes thread/signal crashes because the production code
# exercises macOS-specific signal behavior that Windows cannot emulate.
pytestmark = pytest.mark.skipif(
    os.getenv("GITHUB_ACTIONS") == "true" and sys.platform == "win32",
    reason="macOS adapter mock tests crash on GitHub Actions Windows runners "
           "(signal/thread incompatibility when sys.platform is patched to darwin)",
)

from deskaoy.cascade.protocol import SurfaceAdapter
from deskaoy.cascade.types import AXSnapshot
from deskaoy.results.types import ActionResult


# =================================================================
# Helpers — mock pyobjc modules
# =================================================================

def _mock_pyobjc_modules():
    """Create mock pyobjc modules for testing on non-macOS."""
    app_services = MagicMock()
    core_graphics = MagicMock()
    quartz = MagicMock()

    # Setup Quartz constants
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


def _make_adapter(**kwargs):
    """Create a MacOSAdapter with mocked pyobjc."""
    macos_modules = _mock_pyobjc_modules()
    with patch.dict('sys.modules', macos_modules):
        # Patch sys.platform so _ensure_imports doesn't reject us
        with patch.object(sys, 'platform', 'darwin'):
            from deskaoy.adapters.macos import MacOSAdapter
            adapter = MacOSAdapter(**kwargs)
            # Pre-inject mock modules
            adapter._app_services = macos_modules['ApplicationServices']
            adapter._core_graphics = macos_modules['CoreGraphics']
            adapter._quartz = macos_modules['Quartz']
            adapter._imported = True
            return adapter


# =================================================================
# TASK-01: MacOSAdapter Core (20 tests)
# =================================================================

class TestMacOSAdapterProtocol:
    """MacOSAdapter implements the SurfaceAdapter protocol."""

    def test_is_surface_adapter(self):
        adapter = _make_adapter(pid=123)
        assert isinstance(adapter, SurfaceAdapter)

    def test_is_surface_adapter_with_bundle_id(self):
        adapter = _make_adapter(bundle_id="com.apple.Safari")
        assert isinstance(adapter, SurfaceAdapter)

    def test_constructor_stores_pid(self):
        adapter = _make_adapter(pid=999)
        assert adapter._pid == 999

    def test_constructor_stores_bundle_id(self):
        adapter = _make_adapter(bundle_id="com.apple.TextEdit")
        assert adapter._bundle_id == "com.apple.TextEdit"

    def test_constructor_stores_window_title(self):
        adapter = _make_adapter(window_title="My Window")
        assert adapter._window_title == "My Window"


class TestMacOSAdapterScreenshot:
    """screenshot() uses CGWindowListCreateImage."""

    @pytest.mark.asyncio
    async def test_screenshot_returns_bytes(self):
        adapter = _make_adapter(pid=100)
        # Pre-set window bounds to avoid AXUIElement calls
        adapter._window_bounds = (0, 0, 800, 600)
        # Mock CGWindowListCreateImage to return a truthy image
        adapter._quartz.CGWindowListCreateImage.return_value = MagicMock()
        # Mock the image conversion chain
        mock_rep = MagicMock()
        mock_png = b'\x89PNG\r\n\x1a\n'
        mock_rep.representationUsingType_property_.return_value = mock_png
        adapter._core_graphics.NSBitmapImageRep.alloc.return_value\
            .initWithCGImage_.return_value = mock_rep

        result = await adapter.screenshot()
        assert isinstance(result, bytes)

    @pytest.mark.asyncio
    async def test_screenshot_returns_empty_on_no_image(self):
        adapter = _make_adapter(pid=100)
        adapter._window_bounds = (0, 0, 800, 600)
        adapter._quartz.CGWindowListCreateImage.return_value = None
        result = await adapter.screenshot()
        assert result == b""


class TestMacOSAdapterSnapshot:
    """snapshot() walks the AX tree."""

    @pytest.mark.asyncio
    async def test_snapshot_returns_ax_snapshot(self):
        adapter = _make_adapter(pid=100)
        # Mock AXUIElement to return empty tree
        adapter._app_services.AXUIElementCopyAttributeValue.return_value = (0, [])

        result = await adapter.snapshot()
        assert isinstance(result, AXSnapshot)
        assert result.url.startswith("macos://")

    @pytest.mark.asyncio
    async def test_snapshot_url_uses_pid(self):
        adapter = _make_adapter(pid=42)
        adapter._app_services.AXUIElementCopyAttributeValue.return_value = (0, [])
        result = await adapter.snapshot()
        assert "pid/42" in result.url

    @pytest.mark.asyncio
    async def test_snapshot_url_uses_bundle_id(self):
        # bundle_id-only adapter: snapshot will fail to resolve AX element
        # but the URL is set from current_url() which uses bundle_id
        adapter = _make_adapter(bundle_id="com.apple.Safari")
        # Pre-set AX element so _resolve_ax_element doesn't raise
        adapter._ax_ui = MagicMock()
        adapter._app_services.AXUIElementCopyAttributeValue.return_value = (0, [])
        result = await adapter.snapshot()
        assert "com.apple.Safari" in result.url


class TestMacOSAdapterClick:
    """click() uses CGEvent mouse events."""

    @pytest.mark.asyncio
    async def test_click_dry_run(self):
        adapter = _make_adapter(pid=100)
        result = await adapter.click("500,300", dry_run=True)
        assert result.ok is True
        assert result.data["dry_run"] is True

    @pytest.mark.asyncio
    async def test_click_with_coordinates(self):
        adapter = _make_adapter(pid=100)
        result = await adapter.click("500,300")
        assert result.ok is True
        assert result.data["x"] == 500.0
        assert result.data["y"] == 300.0
        # Verify CGEvent calls were made
        adapter._quartz.CGEventCreateMouseEvent.assert_called()
        adapter._quartz.CGEventPost.assert_called()

    @pytest.mark.asyncio
    async def test_click_returns_pattern_used(self):
        adapter = _make_adapter(pid=100)
        result = await adapter.click("100,200")
        assert result.data["pattern_used"] == "CGEvent"


class TestMacOSAdapterFill:
    """fill() uses click + type."""

    @pytest.mark.asyncio
    async def test_fill_dry_run(self):
        adapter = _make_adapter(pid=100)
        result = await adapter.fill("field", "hello", dry_run=True)
        assert result.ok is True
        assert result.data["dry_run"] is True

    @pytest.mark.asyncio
    async def test_fill_clicks_then_types(self):
        adapter = _make_adapter(pid=100)
        result = await adapter.fill("100,200", "test")
        assert result.ok is True
        assert result.data["value"] == "test"


class TestMacOSAdapterTypeText:
    """type_text() uses CGEvent keyboard events."""

    @pytest.mark.asyncio
    async def test_type_text_dry_run(self):
        adapter = _make_adapter(pid=100)
        result = await adapter.type_text("hello", dry_run=True)
        assert result.ok is True
        assert result.data["dry_run"] is True
        assert result.data["char_count"] == 5

    @pytest.mark.asyncio
    async def test_type_text_sends_key_events(self):
        adapter = _make_adapter(pid=100)
        result = await adapter.type_text("AB")
        assert result.ok is True
        # Should have called CGEventCreateKeyboardEvent for each char (down + up = 4)
        assert adapter._quartz.CGEventCreateKeyboardEvent.call_count == 4


class TestMacOSAdapterKeyPress:
    """key_press() uses CGEvent keyboard events with modifiers."""

    @pytest.mark.asyncio
    async def test_key_press_dry_run(self):
        adapter = _make_adapter(pid=100)
        result = await adapter.key_press("enter", dry_run=True)
        assert result.ok is True
        assert result.data["dry_run"] is True

    @pytest.mark.asyncio
    async def test_key_press_sends_events(self):
        adapter = _make_adapter(pid=100)
        result = await adapter.key_press("return")
        assert result.ok is True
        adapter._quartz.CGEventCreateKeyboardEvent.assert_called()

    @pytest.mark.asyncio
    async def test_key_press_with_modifiers(self):
        adapter = _make_adapter(pid=100)
        result = await adapter.key_press("c", modifiers=8)  # Cmd+C
        assert result.ok is True
        adapter._quartz.CGEventSetFlags.assert_called()


class TestMacOSAdapterCurrentUrl:
    """current_url() returns macos:// scheme."""

    def test_url_with_pid(self):
        adapter = _make_adapter(pid=42)
        assert adapter.current_url() == "macos://pid/42"

    def test_url_with_bundle_id(self):
        adapter = _make_adapter(bundle_id="com.apple.Safari")
        assert adapter.current_url() == "macos://com.apple.Safari"

    def test_url_unknown(self):
        adapter = _make_adapter()
        assert adapter.current_url() == "macos://unknown"
