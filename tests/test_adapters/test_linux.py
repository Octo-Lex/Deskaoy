"""Tests for LinuxAdapter (BATCH-34 TASK-01).

All AT-SPI2 interactions are mocked — no Linux hardware required.
Uses sys.modules patching to provide fake gi/Atspi modules.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from deskaoy.cascade.types import AXSnapshot
from deskaoy.results.types import ErrorCategory

# ---------------------------------------------------------------------------
# Fixtures: mock AT-SPI2 modules
# ---------------------------------------------------------------------------

def _linux_modules():
    """Return the mock module dict for patching sys.modules."""
    gi = MagicMock()
    gi_repo = MagicMock()
    atspi = MagicMock()
    gi.repository = gi_repo
    gi_repo.Atspi = atspi
    pyatspi = MagicMock()
    pyatspi.Registry = MagicMock()
    return {
        "gi": gi,
        "gi.repository": gi_repo,
        "gi.repository.Atspi": atspi,
        "pyatspi": pyatspi,
    }


@pytest.fixture(autouse=True)
def _patch_atspi():
    """Auto-patch AT-SPI2 modules for all tests in this module."""
    modules = _linux_modules()
    with patch.dict("sys.modules", modules):
        yield modules


def _import_adapter():
    """Import LinuxAdapter with mocked atspi in sys.modules."""
    # Must import inside the patch context
    from deskaoy.adapters.linux import LinuxAdapter
    return LinuxAdapter


# ---------------------------------------------------------------------------
# TASK-01 Tests: LinuxAdapter Core (18 tests)
# ---------------------------------------------------------------------------

class TestLinuxAdapterConstruction:
    """Construction and lazy import tests."""

    def test_construct_default(self):
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        assert adapter is not None
        assert adapter._atspi is None  # Not yet imported

    def test_construct_with_humanization(self):
        LinuxAdapter = _import_adapter()
        cfg = MagicMock()
        adapter = LinuxAdapter(humanization=cfg)
        assert adapter._humanization is cfg

    def test_lazy_import_populates_atspi(self):
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        assert adapter._atspi is None
        adapter._ensure_imports()
        assert adapter._atspi is not None

    def test_lazy_import_idempotent(self):
        """Second call to _ensure_imports does not re-import."""
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        adapter._ensure_imports()
        first = adapter._atspi
        adapter._ensure_imports()
        assert adapter._atspi is first


class TestLinuxAdapterScreenshot:
    """Screenshot tests."""

    def test_screenshot_returns_bytes(self):
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        # Mock PIL.ImageGrab
        mock_img = MagicMock()
        mock_buf = MagicMock()
        mock_buf.getvalue.return_value = b"\x89PNG\r\n"

        with patch.dict("sys.modules", {"PIL": MagicMock(), "PIL.ImageGrab": MagicMock()}) as mods:
            mods["PIL"].ImageGrab.grab.return_value = mock_img
            mock_img.save = MagicMock(side_effect=lambda buf, **kw: None)

            with patch("io.BytesIO", return_value=mock_buf):
                result = asyncio.run(adapter.screenshot())
        assert isinstance(result, bytes)

    def test_screenshot_ensure_imports_called(self):
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        # Verify _ensure_imports is called (sets _atspi)
        mock_img = MagicMock()
        with patch.dict("sys.modules", {"PIL": MagicMock(), "PIL.ImageGrab": MagicMock()}) as mods:
            mods["PIL"].ImageGrab.grab.return_value = mock_img
            mock_buf = MagicMock()
            mock_buf.getvalue.return_value = b"png"
            with patch("io.BytesIO", return_value=mock_buf):
                asyncio.run(adapter.screenshot())
        assert adapter._atspi is not None  # Import was triggered


class TestLinuxAdapterSnapshot:
    """AT-SPI2 tree snapshot tests."""

    def test_snapshot_returns_ax_snapshot(self):
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        result = asyncio.run(adapter.snapshot())
        assert isinstance(result, AXSnapshot)

    def test_snapshot_has_linux_url(self):
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        result = asyncio.run(adapter.snapshot())
        assert "x11://" in result.url

    def test_snapshot_walks_tree(self):
        """Snapshot walks AT-SPI2 tree producing nodes."""
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        adapter._ensure_imports()

        # Create mock accessible tree
        child = MagicMock()
        child.get_role.return_value = 1  # button
        child.get_name.return_value = "OK"
        child.get_extents.return_value = MagicMock(x=10, y=20, width=80, height=30)
        child.get_child_count.return_value = 0

        desktop = MagicMock()
        desktop.get_role.return_value = 16  # window
        desktop.get_name.return_value = "Desktop"
        desktop.get_extents.return_value = MagicMock(x=0, y=0, width=1920, height=1080)
        desktop.get_child_count.return_value = 1
        desktop.get_child_at_index.return_value = child

        adapter._atspi.get_desktop.return_value = desktop

        result = asyncio.run(adapter.snapshot())
        assert len(result.nodes) >= 2  # desktop + child

    def test_snapshot_handles_error_gracefully(self):
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        adapter._ensure_imports()
        adapter._atspi.get_desktop.side_effect = RuntimeError("no display")
        result = asyncio.run(adapter.snapshot())
        assert isinstance(result, AXSnapshot)
        assert result.url == "x11://unknown"


class TestLinuxAdapterClick:
    """Click action tests."""

    def test_click_dry_run(self):
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        result = asyncio.run(adapter.click("button", dry_run=True))
        assert result.ok is True
        assert result.data.get("dry_run") is True

    def test_click_finds_accessible(self):
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        adapter._ensure_imports()

        # Mock accessible with action
        acc = MagicMock()
        acc.get_name.return_value = "OK"
        action_iface = MagicMock()
        action_iface.get_nActions.return_value = 1
        action_iface.get_name.return_value = "click"
        acc.queryAction.return_value = action_iface

        desktop = MagicMock()
        desktop.get_name.return_value = "Desktop"
        desktop.get_child_count.return_value = 1
        desktop.get_child_at_index.return_value = acc
        acc.get_child_count.return_value = 0
        adapter._atspi.get_desktop.return_value = desktop

        result = asyncio.run(adapter.click("OK"))
        assert result.ok is True

    def test_click_coordinate_fallback_unsupported_without_xdotool(self):
        """Without xdotool, coordinate click must return UNSUPPORTED."""
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        adapter._ensure_imports()

        desktop = MagicMock()
        desktop.get_name.return_value = "Desktop"
        desktop.get_child_count.return_value = 0
        adapter._atspi.get_desktop.return_value = desktop

        with patch("shutil.which", return_value=None):
            result = asyncio.run(adapter.click("100,200"))
        assert result.ok is False
        assert result.error.category == ErrorCategory.UNSUPPORTED


class TestLinuxAdapterFill:
    """Fill action tests."""

    def test_fill_dry_run(self):
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        result = asyncio.run(adapter.fill("textbox", "hello", dry_run=True))
        assert result.ok is True
        assert result.data.get("dry_run") is True

    def test_fill_returns_unsupported(self):
        """fill returns unsupported when xdotool is not available."""
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()

        with patch("shutil.which", return_value=None):
            result = asyncio.run(adapter.fill("field", "hello"))
        assert result.ok is False
        assert result.error.category == ErrorCategory.UNSUPPORTED
        assert "unsupported" in str(result.error.category).lower()


class TestLinuxAdapterTypeText:
    """Type text action tests."""

    def test_type_text_dry_run(self):
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        result = asyncio.run(adapter.type_text("hello", dry_run=True))
        assert result.ok is True
        assert result.data.get("dry_run") is True

    def test_type_text_returns_unsupported(self):
        """type_text returns unsupported when xdotool is not available."""
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        with patch("shutil.which", return_value=None):
            result = asyncio.run(adapter.type_text("hello"))
        assert result.ok is False


class TestLinuxAdapterKeyPress:
    """Key press action tests."""

    def test_key_press_dry_run(self):
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        result = asyncio.run(adapter.key_press("Enter", dry_run=True))
        assert result.ok is True
        assert result.data.get("dry_run") is True

    def test_key_press_blocked_combo(self):
        """Blocked key combos are rejected."""
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        adapter._ensure_imports()
        # Ctrl+Alt+Delete should be blocked
        result = asyncio.run(adapter.key_press("delete", modifiers=3))  # alt=1, ctrl=2
        assert result.ok is False


class TestLinuxAdapterProperties:
    """Property tests."""

    def test_supports_navigation_false(self):
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        assert adapter.supports_navigation is False

    def test_supports_select_false(self):
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        assert adapter.supports_select is False

    def test_current_url(self):
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        assert "x11://" in adapter.current_url()

    def test_evaluate_returns_none(self):
        LinuxAdapter = _import_adapter()
        adapter = LinuxAdapter()
        result = asyncio.run(adapter.evaluate("anything"))
        assert result is None
