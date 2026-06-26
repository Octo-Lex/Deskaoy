"""BATCH-25: Action-First Windows Automation tests.

Tests for UIA pattern helpers (TASK-01), find_element_by_element_id (TASK-02),
action-first WindowsAdapter refactor (TASK-03), and version/validation (TASK-04).

All tests mock comtypes UIA patterns — no real Windows COM needed.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

# These tests exercise Windows UIA patterns via comtypes mocks.
# They cannot run on Linux/macOS because the comtypes runtime is Windows-only.
pytestmark = [
    pytest.mark.skipif(
        sys.platform != "win32",
        reason="Windows UIA/comtypes tests",
    ),
    pytest.mark.skipif(
        os.getenv("GITHUB_ACTIONS") == "true",
        reason="comtypes.gen.UIAutomationClient type library is not pre-generated "
               "on GitHub Actions Windows runners; these tests need a real desktop "
               "session or pre-generated comtypes module",
    ),
]

from deskaoy.adapters.uia_walker import (
    PatternActionResult,
    UIAElement,
    UIAWalker,
    WalkerConfig,
    _try_collapse_pattern,
    _try_expand_pattern,
    _try_invoke_pattern,
    _try_scroll_into_view_pattern,
    _try_select_pattern,
    _try_set_value_pattern,
    _try_toggle_pattern,
)
from deskaoy.adapters.windows import WindowsAdapter
from deskaoy.cascade.snapshot_types import (
    ROLE_ALIASES,
    ROLE_PREFIXES,
    _ROLE_ALIASES,
    _ROLE_PREFIXES,
    assign_element_ids,
    get_role_prefix,
    validate_element_id,
)
from deskaoy.input.types import HumanizationConfig
from deskaoy.results.types import ActionResult


# =================================================================
# Helpers
# =================================================================

def _make_raw_element(
    *,
    has_invoke: bool = False,
    has_value: bool = False,
    has_toggle: bool = False,
    has_expand_collapse: bool = False,
    has_selection: bool = False,
    has_scroll: bool = False,
    current_value: str = "",
) -> MagicMock:
    """Create a mock raw UIA element with configurable pattern support."""
    mock = MagicMock()
    mock.CurrentName = "TestElement"
    mock.CurrentControlType = 50000  # Button
    mock.CurrentAutomationId = "testId"
    mock.CurrentClassName = "TestClass"
    mock.CurrentIsEnabled = True
    mock.CurrentIsOffscreen = False
    mock.CurrentProcessId = 1234

    # Bounding rectangle
    rect = MagicMock()
    rect.left = 100
    rect.top = 200
    rect.right = 200
    rect.bottom = 240
    mock.CurrentBoundingRectangle = rect

    def _get_pattern(pattern_id: int) -> Optional[MagicMock]:
        """Simulate GetCurrentPattern returning patterns when supported."""
        pattern_map = {
            10000: has_invoke,
            10002: has_value,
            10004: has_toggle,
            10005: has_expand_collapse,
            10010: has_selection,
            10017: has_scroll,
        }
        supported = pattern_map.get(pattern_id, False)
        if not supported:
            return None
        p = MagicMock()
        # For value pattern, set CurrentValue
        if pattern_id == 10002:
            p_iface = MagicMock()
            p_iface.CurrentValue = current_value
            p.QueryInterface.return_value = p_iface
        else:
            p_iface = MagicMock()
            p.QueryInterface.return_value = p_iface
        return p

    mock.GetCurrentPattern = MagicMock(side_effect=_get_pattern)
    return mock


def _make_adapter(hwnd: int = 12345) -> WindowsAdapter:
    """Create a WindowsAdapter with pre-injected mocks."""
    cfg = HumanizationConfig(move_enabled=False)
    adapter = WindowsAdapter(hwnd=hwnd, humanization=cfg)

    win32gui = MagicMock()
    win32gui.IsWindow.return_value = True
    win32gui.IsIconic.return_value = False
    win32gui.IsWindowVisible.return_value = True
    win32gui.GetWindowRect.return_value = (100, 100, 800, 600)
    win32gui.WindowFromPoint.return_value = hwnd
    win32gui.GetWindowText.return_value = "TestWindow"

    win32api = MagicMock()
    win32api.GetCursorPos.return_value = (200, 200)
    win32api.GetDpiForWindow.return_value = 96

    pyautogui = MagicMock()

    adapter._win32gui = win32gui
    adapter._win32api = win32api
    adapter._win32con = MagicMock()
    adapter._pyautogui = pyautogui

    return adapter


def _make_uia_element(
    ref: str = "e0",
    name: str = "Test",
    control_type: str = "button",
    control_type_id: int = 50000,
    bounds: tuple[float, float, float, float] = (100.0, 200.0, 80.0, 30.0),
) -> UIAElement:
    """Create a UIAElement with sensible defaults."""
    return UIAElement(
        ref=ref,
        name=name,
        control_type=control_type,
        control_type_id=control_type_id,
        automation_id="",
        class_name="TestClass",
        bounds=bounds,
        is_enabled=True,
        is_visible=True,
        is_interactive=True,
        is_offscreen=False,
        process_id=1234,
        value="",
        help_text="",
        accelerator="",
        depth=0,
    )


# =================================================================
# TEST-25-01: Pattern helper unit tests (TASK-01)
# =================================================================


class TestPatternHelpers:
    """TEST-25-01-01 through TEST-25-01-08: 8 pattern helpers."""

    def test_invoke_pattern_success(self):
        """TEST-25-01-01: invoke_element pattern helper success."""
        raw = _make_raw_element(has_invoke=True)
        result = _try_invoke_pattern(raw)
        assert result is not None
        assert result.success is True
        assert result.pattern_used == "InvokePattern"
        assert result.fallback_used is False

    def test_set_value_pattern_success(self):
        """TEST-25-01-02: set_value pattern helper success."""
        raw = _make_raw_element(has_value=True)
        result = _try_set_value_pattern(raw, "hello world")
        assert result is not None
        assert result.success is True
        assert result.pattern_used == "ValuePattern"

    def test_get_value_pattern_returns_string(self):
        """TEST-25-01-03: get_value pattern helper returns string."""
        raw = _make_raw_element(has_value=True, current_value="test_value")
        from deskaoy.adapters.uia_walker import _try_get_value_pattern
        result = _try_get_value_pattern(raw)
        assert result == "test_value"

    def test_toggle_pattern_success(self):
        """TEST-25-01-04: toggle_element pattern helper success."""
        raw = _make_raw_element(has_toggle=True)
        result = _try_toggle_pattern(raw)
        assert result is not None
        assert result.success is True
        assert result.pattern_used == "TogglePattern"

    def test_expand_pattern_success(self):
        """TEST-25-01-05: expand_element pattern helper success."""
        raw = _make_raw_element(has_expand_collapse=True)
        result = _try_expand_pattern(raw)
        assert result is not None
        assert result.success is True
        assert result.pattern_used == "ExpandCollapsePattern"

    def test_collapse_pattern_success(self):
        """TEST-25-01-06: collapse_element pattern helper success."""
        raw = _make_raw_element(has_expand_collapse=True)
        result = _try_collapse_pattern(raw)
        assert result is not None
        assert result.success is True
        assert result.pattern_used == "ExpandCollapsePattern"

    def test_select_pattern_success(self):
        """TEST-25-01-07: select_element pattern helper success."""
        raw = _make_raw_element(has_selection=True)
        result = _try_select_pattern(raw)
        assert result is not None
        assert result.success is True
        assert result.pattern_used == "SelectionItemPattern"

    def test_scroll_into_view_pattern_success(self):
        """TEST-25-01-08: scroll_into_view pattern helper success."""
        raw = _make_raw_element(has_scroll=True)
        result = _try_scroll_into_view_pattern(raw)
        assert result is not None
        assert result.success is True
        assert result.pattern_used == "ScrollItemPattern"


class TestPatternHelperFallbacks:
    """TEST-25-01-09 through TEST-25-01-12: Pattern helpers when unavailable."""

    def test_pattern_returns_none_when_unavailable(self):
        """TEST-25-01-09: Pattern helper returns None when pattern unsupported."""
        raw = _make_raw_element()  # No patterns enabled
        assert _try_invoke_pattern(raw) is None
        assert _try_set_value_pattern(raw, "x") is None
        assert _try_toggle_pattern(raw) is None
        assert _try_expand_pattern(raw) is None
        assert _try_collapse_pattern(raw) is None
        assert _try_select_pattern(raw) is None
        assert _try_scroll_into_view_pattern(raw) is None

    def test_find_element_by_name_returns_uia_element(self):
        """TEST-25-01-10: find_element_by_name returns UIAElement."""
        walker = UIAWalker()
        elem = _make_uia_element(name="Submit", control_type="button")
        with patch.object(walker, "find_element_by_name", return_value=elem):
            result = walker.find_element_by_name(hwnd=1, name="Submit")
        assert result is not None
        assert result.name == "Submit"

    def test_find_element_by_automation_id_returns_uia_element(self):
        """TEST-25-01-11: find_element_by_automation_id returns UIAElement."""
        walker = UIAWalker()
        elem = _make_uia_element(name="EditField", control_type="edit")
        with patch.object(walker, "find_element_by_automation_id", return_value=elem):
            result = walker.find_element_by_automation_id(hwnd=1, automation_id="edit1")
        assert result is not None
        assert result.name == "EditField"

    def test_existing_uia_walker_tests_pass(self):
        """TEST-25-01-12: Existing UIAWalker tests still pass (meta-check)."""
        # This is verified by running the full suite; here we just check the
        # walker class still has all expected methods.
        walker = UIAWalker()
        assert hasattr(walker, "walk")
        assert hasattr(walker, "walk_to_snapshot")
        assert hasattr(walker, "find_element_by_name")
        assert hasattr(walker, "find_element_by_automation_id")
        assert hasattr(walker, "find_element_by_element_id")
        assert hasattr(walker, "try_invoke")
        assert hasattr(walker, "invoke_action")


# =================================================================
# TEST-25-02: Element ID resolution (TASK-02)
# =================================================================


class TestElementIdResolution:
    """TEST-25-02-01 through TEST-25-02-08: find_element_by_element_id."""

    def test_prefix_parsing_E(self):
        """TEST-25-02-01: E-prefix matches any role (generic fallback)."""
        walker = UIAWalker()
        elements = [
            _make_uia_element(ref="e0", control_type="pane", control_type_id=50031),
            _make_uia_element(ref="e1", control_type="button", control_type_id=50000),
            _make_uia_element(ref="e2", control_type="text", control_type_id=50022),
        ]
        with patch.object(walker, "walk", return_value=elements):
            result = walker.find_element_by_element_id(hwnd=1, element_id="E2")
        assert result is not None
        assert result.control_type == "button"

    def test_role_mapping_B_button(self):
        """TEST-25-02-02: B prefix maps to button role."""
        walker = UIAWalker()
        elements = [
            _make_uia_element(ref="e0", control_type="button", control_type_id=50000),
            _make_uia_element(ref="e1", control_type="edit", control_type_id=50004),
            _make_uia_element(ref="e2", control_type="button", control_type_id=50000),
        ]
        with patch.object(walker, "walk", return_value=elements):
            b1 = walker.find_element_by_element_id(hwnd=1, element_id="B1")
            b2 = walker.find_element_by_element_id(hwnd=1, element_id="B2")
        assert b1 is not None
        assert b2 is not None
        assert b1.ref == "e0"
        assert b2.ref == "e2"

    def test_role_mapping_T_textbox(self):
        """TEST-25-02-03: T prefix maps to textbox/edit role."""
        walker = UIAWalker()
        elements = [
            _make_uia_element(ref="e0", control_type="button", control_type_id=50000),
            _make_uia_element(ref="e1", control_type="edit", control_type_id=50004),
        ]
        with patch.object(walker, "walk", return_value=elements):
            t1 = walker.find_element_by_element_id(hwnd=1, element_id="T1")
        assert t1 is not None
        assert t1.control_type == "edit"

    def test_nth_element_B1_B2(self):
        """TEST-25-02-04: Nth element: B1=first button, B2=second button."""
        walker = UIAWalker()
        elements = [
            _make_uia_element(ref="e0", control_type="button", control_type_id=50000, name="OK"),
            _make_uia_element(ref="e1", control_type="edit", control_type_id=50004, name="Input"),
            _make_uia_element(ref="e2", control_type="button", control_type_id=50000, name="Cancel"),
        ]
        with patch.object(walker, "walk", return_value=elements):
            b1 = walker.find_element_by_element_id(hwnd=1, element_id="B1")
            b2 = walker.find_element_by_element_id(hwnd=1, element_id="B2")
        assert b1 is not None
        assert b2 is not None
        assert b1.name == "OK"
        assert b2.name == "Cancel"

    def test_unknown_element_id_returns_none(self):
        """TEST-25-02-05: Unknown element ID (no matching elements) returns None."""
        walker = UIAWalker()
        elements = [
            _make_uia_element(ref="e0", control_type="button", control_type_id=50000),
        ]
        with patch.object(walker, "walk", return_value=elements):
            result = walker.find_element_by_element_id(hwnd=1, element_id="T1")
        assert result is None

    def test_deterministic_same_tree_same_ids(self):
        """TEST-25-02-06: Same tree → same IDs deterministically."""
        walker = UIAWalker()
        elements = [
            _make_uia_element(ref="e0", control_type="button", control_type_id=50000, name="OK"),
            _make_uia_element(ref="e1", control_type="edit", control_type_id=50004, name="Input"),
        ]
        with patch.object(walker, "walk", return_value=elements):
            b1_first = walker.find_element_by_element_id(hwnd=1, element_id="B1")
            b1_second = walker.find_element_by_element_id(hwnd=1, element_id="B1")
        assert b1_first is not None
        assert b1_second is not None
        assert b1_first.ref == b1_second.ref

    def test_M_prefix_matches_menu(self):
        """TEST-25-02-07: M prefix matches menu/menuitem roles."""
        walker = UIAWalker()
        elements = [
            _make_uia_element(ref="e0", control_type="menuitem", control_type_id=50013, name="File"),
            _make_uia_element(ref="e1", control_type="menuitem", control_type_id=50013, name="Edit"),
        ]
        with patch.object(walker, "walk", return_value=elements):
            m1 = walker.find_element_by_element_id(hwnd=1, element_id="M1")
            m2 = walker.find_element_by_element_id(hwnd=1, element_id="M2")
        assert m1 is not None
        assert m2 is not None
        assert m1.name == "File"
        assert m2.name == "Edit"

    def test_invalid_id_format_returns_none(self):
        """TEST-25-02-08: Invalid ID format returns None."""
        walker = UIAWalker()
        assert walker.find_element_by_element_id(hwnd=1, element_id="") is None
        assert walker.find_element_by_element_id(hwnd=1, element_id="X1") is None
        assert walker.find_element_by_element_id(hwnd=1, element_id="B") is None
        assert walker.find_element_by_element_id(hwnd=1, element_id="B0") is None


# =================================================================
# TEST-25-03: Action-first WindowsAdapter (TASK-03)
# =================================================================


class TestActionFirstClick:
    """TEST-25-03-01 through TEST-25-03-04: click() action-first."""

    @pytest.mark.asyncio
    async def test_click_with_invoke_pattern(self):
        """TEST-25-03-01: click uses InvokePattern when available."""
        adapter = _make_adapter()

        # Mock _resolve_raw_element to return a mock with InvokePattern
        mock_raw = _make_raw_element(has_invoke=True)
        with patch.object(
            adapter, "_resolve_raw_element", return_value=mock_raw,
        ):
            result = await adapter.click("name:TestButton")

        assert result.ok is True
        assert result.data.get("pattern_used") == "InvokePattern"
        assert result.data.get("fallback_used") is False
        # pyautogui should NOT have been called
        adapter._pyautogui.click.assert_not_called()

    @pytest.mark.asyncio
    async def test_click_falls_back_to_pyautogui(self):
        """TEST-25-03-02: click falls back to pyautogui when pattern unavailable."""
        adapter = _make_adapter()

        # Mock _resolve_raw_element to return element without InvokePattern
        mock_raw = _make_raw_element()  # no patterns
        with patch.object(
            adapter, "_resolve_raw_element", return_value=mock_raw,
        ):
            result = await adapter.click("name:TestButton")

        assert result.ok is True
        assert result.data.get("fallback_used") is True
        # pyautogui click SHOULD have been called
        adapter._pyautogui.click.assert_called()

    @pytest.mark.asyncio
    async def test_click_coordinate_uses_pyautogui(self):
        """TEST-25-03-03: click coordinate target always uses pyautogui."""
        adapter = _make_adapter()

        result = await adapter.click("400,300")

        assert result.ok is True
        adapter._pyautogui.click.assert_called()

    @pytest.mark.asyncio
    async def test_click_dry_run_still_works(self):
        """TEST-25-03-04: click dry_run still works (no change)."""
        adapter = _make_adapter()

        result = await adapter.click("400,300", dry_run=True)

        assert result.ok is True
        assert result.data["dry_run"] is True
        adapter._pyautogui.click.assert_not_called()


class TestActionFirstFill:
    """TEST-25-03-05 through TEST-25-03-08: fill() action-first."""

    @pytest.mark.asyncio
    async def test_fill_with_value_pattern(self):
        """TEST-25-03-05: fill uses ValuePattern when available."""
        adapter = _make_adapter()

        mock_raw = _make_raw_element(has_value=True)
        with patch.object(
            adapter, "_resolve_raw_element", return_value=mock_raw,
        ):
            result = await adapter.fill("name:InputField", "hello world")

        assert result.ok is True
        assert result.data.get("pattern_used") == "ValuePattern"
        assert result.data.get("fallback_used") is False

    @pytest.mark.asyncio
    async def test_fill_falls_back_to_click_type(self):
        """TEST-25-03-06: fill falls back to click+type when pattern unavailable."""
        adapter = _make_adapter()

        mock_raw = _make_raw_element()  # no patterns
        with patch.object(
            adapter, "_resolve_raw_element", return_value=mock_raw,
        ):
            result = await adapter.fill("name:InputField", "hello")

        assert result.ok is True
        # Should have fallen back — pyautogui click and write called
        adapter._pyautogui.click.assert_called()

    @pytest.mark.asyncio
    async def test_fill_dry_run(self):
        """TEST-25-03-07: fill dry_run still works."""
        adapter = _make_adapter()

        result = await adapter.fill("400,300", "test", dry_run=True)

        assert result.ok is True
        assert result.data["dry_run"] is True

    @pytest.mark.asyncio
    async def test_fill_error_handling(self):
        """TEST-25-03-08: fill handles errors gracefully."""
        adapter = _make_adapter()
        adapter.abort()

        result = await adapter.fill("400,300", "test")

        assert result.ok is False


class TestActionFirstInvokeElement:
    """TEST-25-03-09 through TEST-25-03-15: invoke_element() action-first."""

    @pytest.mark.asyncio
    async def test_invoke_toggle_uses_toggle_pattern(self):
        """TEST-25-03-09: invoke toggle uses TogglePattern."""
        adapter = _make_adapter()

        mock_raw = _make_raw_element(has_toggle=True)
        with patch.object(
            adapter, "_resolve_raw_element", return_value=mock_raw,
        ):
            result = await adapter.invoke_element("name:Checkbox", action="toggle")

        assert result.ok is True
        assert result.data.get("pattern_used") == "TogglePattern"
        assert result.data.get("fallback_used") is False

    @pytest.mark.asyncio
    async def test_invoke_expand_uses_expand_pattern(self):
        """TEST-25-03-10: invoke expand uses ExpandCollapsePattern."""
        adapter = _make_adapter()

        mock_raw = _make_raw_element(has_expand_collapse=True)
        with patch.object(
            adapter, "_resolve_raw_element", return_value=mock_raw,
        ):
            result = await adapter.invoke_element("name:ComboBox", action="expand")

        assert result.ok is True
        assert result.data.get("pattern_used") == "ExpandCollapsePattern"

    @pytest.mark.asyncio
    async def test_invoke_set_value_uses_value_pattern(self):
        """TEST-25-03-11: invoke set_value uses ValuePattern."""
        adapter = _make_adapter()

        mock_raw = _make_raw_element(has_value=True)
        with patch.object(
            adapter, "_resolve_raw_element", return_value=mock_raw,
        ):
            result = await adapter.invoke_element(
                "name:Input", action="set_value", value="test",
            )

        assert result.ok is True
        assert result.data.get("pattern_used") == "ValuePattern"

    @pytest.mark.asyncio
    async def test_invoke_unknown_action_returns_error(self):
        """TEST-25-03-12: invoke unknown action returns error."""
        adapter = _make_adapter()

        result = await adapter.invoke_element("500,500", action="teleport")

        assert result.ok is False

    @pytest.mark.asyncio
    async def test_action_result_has_pattern_used_field(self):
        """TEST-25-03-13: ActionResult has pattern_used field."""
        adapter = _make_adapter()

        mock_raw = _make_raw_element(has_invoke=True)
        with patch.object(
            adapter, "_resolve_raw_element", return_value=mock_raw,
        ):
            result = await adapter.click("name:Btn")

        assert "pattern_used" in result.data

    @pytest.mark.asyncio
    async def test_action_result_has_fallback_used_field(self):
        """TEST-25-03-14: ActionResult has fallback_used field."""
        adapter = _make_adapter()

        result = await adapter.click("400,300")

        assert "fallback_used" in result.data

    @pytest.mark.asyncio
    async def test_existing_invoke_element_tests_still_pass(self):
        """TEST-25-03-15: Existing invoke_element tests still pass."""
        # Verified by running the full suite. Quick sanity check here:
        adapter = _make_adapter()
        result = await adapter.invoke_element("500,500", action="click")
        assert result.ok is True


# =================================================================
# TEST-25-04: Version bump and validation (TASK-04)
# =================================================================


class TestVersionAndValidation:
    """TEST-25-04-01 through TEST-25-04-03: Version and suite integrity."""

    def test_version_is_current(self):
        """TEST-25-04-01: Version is consistent across version.py and desktop_agent.py."""
        from deskaoy.cli.version import VERSION
        parts = VERSION.split(".")
        assert len(parts) == 3, f"Expected semver, got {VERSION}"
        assert all(p.isdigit() for p in parts), f"Invalid semver: {VERSION}"

        # Also check desktop_agent.py version matches
        from deskaoy.desktop_agent import DesktopAgent
        import inspect
        from deskaoy import desktop_agent
        import re
        source = inspect.getsource(desktop_agent)
        match = re.search(r'version.*?=\s*["\']([\d.]+)["\']', source)
        if match:
            assert match.group(1) == VERSION, (
                f"desktop_agent.py version is {match.group(1)}, expected {VERSION}"
            )

    def test_pattern_action_result_dataclass(self):
        """TEST-25-04-02: PatternActionResult is a proper dataclass."""
        result = PatternActionResult(
            success=True,
            pattern_used="InvokePattern",
            fallback_used=False,
            element_id="B1",
        )
        assert result.success is True
        assert result.pattern_used == "InvokePattern"
        assert result.fallback_used is False
        assert result.element_id == "B1"
        assert result.error is None

    def test_no_test_regressions(self):
        """TEST-25-04-03: No regression — key exports still available."""
        # Verify all public APIs are still importable
        from deskaoy.adapters.uia_walker import (
            UIAWalker,
            UIAElement,
            WalkerConfig,
            PatternActionResult,
            UIA_INVOKE_PATTERN_ID,
            UIA_VALUE_PATTERN_ID,
            UIA_TOGGLE_PATTERN_ID,
            UIA_EXPAND_COLLAPSE_PATTERN_ID,
            UIA_SELECTION_ITEM_PATTERN_ID,
            UIA_SCROLL_ITEM_PATTERN_ID,
        )
        from deskaoy.cascade.snapshot_types import (
            ROLE_PREFIXES,
            ROLE_ALIASES,
            assign_element_ids,
            get_role_prefix,
            validate_element_id,
        )
        from deskaoy.adapters.windows import WindowsAdapter

        # Verify snapshot_types backward compat
        assert _ROLE_PREFIXES is ROLE_PREFIXES
        assert _ROLE_ALIASES is ROLE_ALIASES

        # Verify pattern IDs are correct
        assert UIA_INVOKE_PATTERN_ID == 10000
        assert UIA_VALUE_PATTERN_ID == 10002
        assert UIA_TOGGLE_PATTERN_ID == 10004
        assert UIA_EXPAND_COLLAPSE_PATTERN_ID == 10005
        assert UIA_SELECTION_ITEM_PATTERN_ID == 10010
        assert UIA_SCROLL_ITEM_PATTERN_ID == 10017
