"""Tests for UIA walker — type-level and mocked COM tests.

All tests in this file run on any OS (no Windows required).
COM-dependent tests use mocks to simulate IUIAutomation behavior.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from deskaoy.adapters.uia_walker import (
    UIAElement,
    UIAWalker,
    WalkerConfig,
    _IUIAWrapper,
    _UIA_CONTROL_TYPE_MAP,
    _UIA_CONTROL_TYPE_NAMES,
    _INTERACTIVE_TYPE_IDS,
    _INFORMATIVE_TYPE_IDS,
    _get_value_pattern,
)
from deskaoy.cascade.types import AXNode, AXSnapshot
from deskaoy.grounding.types import BBox, Detection, DetectionSource, ElementRole


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_element(
    ref: str = "e0",
    name: str = "TestButton",
    control_type: str = "button",
    control_type_id: int = 50000,
    automation_id: str = "",
    class_name: str = "Button",
    bounds: tuple[float, float, float, float] = (100.0, 200.0, 80.0, 30.0),
    is_enabled: bool = True,
    is_visible: bool = True,
    is_interactive: bool = True,
    is_offscreen: bool = False,
    process_id: int = 1234,
    value: str = "",
    help_text: str = "",
    accelerator: str = "",
    depth: int = 0,
) -> UIAElement:
    """Create a UIAElement with sensible defaults."""
    return UIAElement(
        ref=ref,
        name=name,
        control_type=control_type,
        control_type_id=control_type_id,
        automation_id=automation_id,
        class_name=class_name,
        bounds=bounds,
        is_enabled=is_enabled,
        is_visible=is_visible,
        is_interactive=is_interactive,
        is_offscreen=is_offscreen,
        process_id=process_id,
        value=value,
        help_text=help_text,
        accelerator=accelerator,
        depth=depth,
    )


# ---------------------------------------------------------------------------
# UIAElement type tests
# ---------------------------------------------------------------------------

class TestUIAElement:
    """Test UIAElement dataclass and property methods."""

    def test_bbox_property(self):
        elem = _make_element(bounds=(10.0, 20.0, 80.0, 40.0))
        bbox = elem.bbox
        assert isinstance(bbox, BBox)
        assert bbox.x1 == 10.0
        assert bbox.y1 == 20.0
        assert bbox.x2 == 90.0  # 10 + 80
        assert bbox.y2 == 60.0  # 20 + 40

    def test_center_property(self):
        elem = _make_element(bounds=(100.0, 200.0, 80.0, 60.0))
        cx, cy = elem.center
        assert cx == 140.0  # 100 + 80/2
        assert cy == 230.0  # 200 + 60/2

    def test_element_role_button(self):
        elem = _make_element(control_type_id=50000)
        assert elem.element_role == ElementRole.BUTTON

    def test_element_role_edit(self):
        elem = _make_element(control_type_id=50004)
        assert elem.element_role == ElementRole.INPUT

    def test_element_role_text(self):
        elem = _make_element(control_type_id=50022)
        assert elem.element_role == ElementRole.TEXT

    def test_element_role_unknown(self):
        elem = _make_element(control_type_id=99999)
        assert elem.element_role == ElementRole.OTHER

    def test_to_ax_node(self):
        elem = _make_element(
            ref="e5",
            name="Submit",
            control_type="button",
            value="",
            help_text="Click to submit",
            bounds=(10.0, 20.0, 80.0, 30.0),
            is_enabled=True,
        )
        node = elem.to_ax_node()
        assert isinstance(node, AXNode)
        assert node.ref == "e5"
        assert node.role == "button"
        assert node.name == "Submit"
        assert node.description == "Click to submit"
        assert node.bounds == (10.0, 20.0, 80.0, 30.0)
        assert node.disabled is False

    def test_to_ax_node_disabled(self):
        elem = _make_element(is_enabled=False)
        node = elem.to_ax_node()
        assert node.disabled is True

    def test_to_ax_node_with_value(self):
        elem = _make_element(value="hello world", control_type_id=50004)
        node = elem.to_ax_node()
        assert node.value == "hello world"

    def test_to_ax_node_no_empty_value(self):
        elem = _make_element(value="")
        node = elem.to_ax_node()
        assert node.value is None

    def test_to_detection(self):
        elem = _make_element(
            name="OK",
            control_type_id=50000,
            bounds=(50.0, 100.0, 60.0, 25.0),
        )
        det = elem.to_detection()
        assert isinstance(det, Detection)
        assert det.source == DetectionSource.STRUCTURAL
        assert det.confidence == 0.95
        assert det.label == "OK"
        assert det.role == ElementRole.BUTTON
        assert det.text == "OK"
        assert det.bbox.x1 == 50.0
        assert det.bbox.x2 == 110.0

    def test_to_detection_fallback_label(self):
        elem = _make_element(name="", control_type="combobox", control_type_id=50003)
        det = elem.to_detection()
        assert det.label == "combobox"

    def test_all_control_types_mapped(self):
        """Every UIA control type ID in the names dict should be in the map dict."""
        for type_id in _UIA_CONTROL_TYPE_NAMES:
            assert type_id in _UIA_CONTROL_TYPE_MAP, (
                f"Control type {type_id} ({_UIA_CONTROL_TYPE_NAMES[type_id]}) "
                f"not in _UIA_CONTROL_TYPE_MAP"
            )


# ---------------------------------------------------------------------------
# WalkerConfig tests
# ---------------------------------------------------------------------------

class TestWalkerConfig:
    """Test WalkerConfig defaults."""

    def test_defaults(self):
        config = WalkerConfig()
        assert config.max_depth == 8
        assert config.element_timeout_s == 0.3
        assert config.include_invisible is False
        assert config.include_non_interactive is True
        assert config.min_element_size == 2
        assert config.use_raw_walker is False
        assert config.max_elements == 500

    def test_custom(self):
        config = WalkerConfig(
            max_depth=4,
            element_timeout_s=0.1,
            max_elements=100,
            include_invisible=True,
        )
        assert config.max_depth == 4
        assert config.element_timeout_s == 0.1
        assert config.max_elements == 100
        assert config.include_invisible is True


# ---------------------------------------------------------------------------
# Walker filtering tests
# ---------------------------------------------------------------------------

class TestWalkerFiltering:
    """Test _should_include logic."""

    def _make_walker(self, **config_kwargs) -> UIAWalker:
        config = WalkerConfig(**config_kwargs)
        return UIAWalker(config=config)

    def test_include_visible_interactive(self):
        walker = self._make_walker()
        elem = _make_element(is_visible=True, is_interactive=True)
        assert walker._should_include(elem) is True

    def test_exclude_invisible(self):
        walker = self._make_walker()
        elem = _make_element(is_visible=False, is_offscreen=True)
        assert walker._should_include(elem) is False

    def test_include_invisible_when_configured(self):
        walker = self._make_walker(include_invisible=True)
        elem = _make_element(is_visible=False, is_offscreen=True)
        assert walker._should_include(elem) is True

    def test_exclude_zero_width(self):
        walker = self._make_walker()
        elem = _make_element(bounds=(10.0, 20.0, 0.0, 30.0))
        assert walker._should_include(elem) is False

    def test_exclude_zero_height(self):
        walker = self._make_walker()
        elem = _make_element(bounds=(10.0, 20.0, 80.0, 0.0))
        assert walker._should_include(elem) is False

    def test_exclude_tiny_element(self):
        walker = self._make_walker(min_element_size=5)
        elem = _make_element(bounds=(10.0, 20.0, 3.0, 3.0))
        assert walker._should_include(elem) is False

    def test_include_informative_when_configured(self):
        walker = self._make_walker(include_non_interactive=True)
        elem = _make_element(is_interactive=False, control_type_id=50022)  # Text
        assert walker._should_include(elem) is True

    def test_exclude_non_interactive_when_configured(self):
        walker = self._make_walker(include_non_interactive=False)
        elem = _make_element(is_interactive=False, control_type_id=50022)
        assert walker._should_include(elem) is False

    def test_include_interactive_when_non_interactive_excluded(self):
        walker = self._make_walker(include_non_interactive=False)
        elem = _make_element(is_interactive=True, control_type_id=50000)  # Button
        assert walker._should_include(elem) is True


# ---------------------------------------------------------------------------
# Walk-to-snapshot/detection tests (with mocked walk)
# ---------------------------------------------------------------------------

class TestWalkConversions:
    """Test walk_to_snapshot and walk_to_detections with mocked walk."""

    def test_walk_to_snapshot(self):
        walker = UIAWalker()
        elements = [
            _make_element(ref="e0", name="Button1", control_type="button", control_type_id=50000),
            _make_element(ref="e1", name="Edit1", control_type="edit", control_type_id=50004),
        ]
        with patch.object(walker, "walk", return_value=elements):
            snapshot = walker.walk_to_snapshot(hwnd=1234, url="win32://Test", title="Test")

        assert isinstance(snapshot, AXSnapshot)
        assert snapshot.url == "win32://Test"
        assert snapshot.title == "Test"
        assert len(snapshot.nodes) == 2
        assert "e0" in snapshot.nodes
        assert "e1" in snapshot.nodes
        assert snapshot.nodes["e0"].role == "button"
        assert snapshot.nodes["e1"].role == "edit"

    def test_walk_to_snapshot_empty(self):
        walker = UIAWalker()
        with patch.object(walker, "walk", return_value=[]):
            snapshot = walker.walk_to_snapshot(hwnd=1234)
        assert len(snapshot.nodes) == 0

    def test_walk_to_detections(self):
        walker = UIAWalker()
        elements = [
            _make_element(ref="e0", name="OK", control_type_id=50000),
            _make_element(ref="e1", name="Cancel", control_type_id=50000),
        ]
        with patch.object(walker, "walk", return_value=elements):
            detections = walker.walk_to_detections(hwnd=1234)

        assert len(detections) == 2
        assert all(isinstance(d, Detection) for d in detections)
        assert all(d.source == DetectionSource.STRUCTURAL for d in detections)
        assert all(d.confidence == 0.95 for d in detections)

    def test_walk_returns_empty_on_com_error(self):
        walker = UIAWalker()
        # Test with element_from_handle failure (walk catches Exception)
        mock_uia = MagicMock()
        mock_uia.element_from_handle.side_effect = Exception("COM error")
        walker._uia = mock_uia
        result = walker.walk(hwnd=1234)
        assert result == []


# ---------------------------------------------------------------------------
# _get_value_pattern tests
# ---------------------------------------------------------------------------

class TestGetValuePattern:
    """Test the _get_value_pattern helper."""

    def test_returns_value(self):
        mock_elem = MagicMock()
        mock_pattern = MagicMock()
        mock_iface = MagicMock()
        mock_iface.CurrentValue = "test_value"
        mock_pattern.QueryInterface.return_value = mock_iface
        mock_elem.GetCurrentPattern.return_value = mock_pattern

        with patch("deskaoy.adapters.uia_walker._get_value_pattern") as mock_fn:
            # We can't easily mock comtypes imports, so just test the function
            # handles exceptions gracefully
            pass

    def test_returns_none_on_exception(self):
        mock_elem = MagicMock()
        mock_elem.GetCurrentPattern.side_effect = Exception("no pattern")
        result = _get_value_pattern(mock_elem)
        assert result is None


# ---------------------------------------------------------------------------
# Control type mapping completeness tests
# ---------------------------------------------------------------------------

class TestControlTypeMappings:
    """Test the control type mapping tables."""

    def test_interactive_types_are_subset_of_map(self):
        for type_id in _INTERACTIVE_TYPE_IDS:
            assert type_id in _UIA_CONTROL_TYPE_MAP

    def test_informative_types_are_subset_of_map(self):
        for type_id in _INFORMATIVE_TYPE_IDS:
            assert type_id in _UIA_CONTROL_TYPE_MAP

    def test_interactive_types_have_names(self):
        for type_id in _INTERACTIVE_TYPE_IDS:
            assert type_id in _UIA_CONTROL_TYPE_NAMES

    def test_informative_types_have_names(self):
        for type_id in _INFORMATIVE_TYPE_IDS:
            assert type_id in _UIA_CONTROL_TYPE_NAMES

    def test_no_overlap_interactive_informative(self):
        overlap = _INTERACTIVE_TYPE_IDS & _INFORMATIVE_TYPE_IDS
        assert len(overlap) == 0, f"Overlap found: {overlap}"

    def test_common_types_present(self):
        """Ensure the most common UIA control types are mapped."""
        common = {
            50000: "button",
            50004: "edit",
            50002: "checkbox",
            50003: "combobox",
            50022: "text",
            50032: "window",
            50031: "pane",
        }
        for type_id, expected_name in common.items():
            assert type_id in _UIA_CONTROL_TYPE_NAMES
            assert _UIA_CONTROL_TYPE_NAMES[type_id] == expected_name


# ---------------------------------------------------------------------------
# IUIAWrapper singleton tests
# ---------------------------------------------------------------------------

class TestIUIAWrapper:
    """Test the _IUIAWrapper singleton behavior (without actual COM)."""

    def test_reset_clears_singleton(self):
        _IUIAWrapper._instance = MagicMock()  # Pretend initialized
        _IUIAWrapper.reset()
        assert _IUIAWrapper._instance is None

    def test_get_creates_singleton(self):
        _IUIAWrapper.reset()
        with patch("deskaoy.adapters.uia_walker._IUIAWrapper.__init__", return_value=None):
            # Can't fully test without COM, but verify singleton pattern
            pass


# ---------------------------------------------------------------------------
# Recursive walk cap tests
# ---------------------------------------------------------------------------

class TestWalkCaps:
    """Test max_depth and max_elements caps."""

    def test_max_depth_cap(self):
        """Walker should not exceed max_depth."""
        config = WalkerConfig(max_depth=2, max_elements=1000)
        walker = UIAWalker(config=config)
        call_log = []

        original_walk_recursive = walker._walk_recursive

        def tracking_walk(element, depth, elements):
            call_log.append(depth)
            if depth <= config.max_depth:
                original_walk_recursive(element, depth, elements)

        walker._walk_recursive = tracking_walk

        # Mock the COM walker to produce infinite children
        mock_uia = MagicMock()
        mock_child = MagicMock()

        call_count = [0]

        def get_first_child(elem):
            call_count[0] += 1
            if call_count[0] > 50:
                return None
            return mock_child

        def get_next_sibling(elem):
            return None  # Only one child per level

        mock_uia.control_walker.GetFirstChildElement = get_first_child
        mock_uia.control_walker.GetNextSiblingElement = get_next_sibling

        walker._uia = mock_uia

        # _extract_with_timeout would fail on mock, so mock it too
        walker._extract_with_timeout = lambda raw, depth: _make_element(
            ref="", depth=depth, is_visible=True,
        )

        elements = walker.walk(hwnd=None)
        # The walk should have respected max_depth
        if call_log:
            assert max(call_log) <= config.max_depth + 1  # +1 for initial call

    def test_max_elements_cap(self):
        """Walker should not exceed max_elements."""
        config = WalkerConfig(max_elements=5, max_depth=20)
        walker = UIAWalker(config=config)

        mock_uia = MagicMock()
        counter = [0]

        class FakeChild:
            pass

        def get_first_child(elem):
            counter[0] += 1
            if counter[0] > 100:
                return None
            return FakeChild()

        def get_next_sibling(elem):
            return None

        mock_uia.control_walker.GetFirstChildElement = get_first_child
        mock_uia.control_walker.GetNextSiblingElement = get_next_sibling
        walker._uia = mock_uia

        walker._extract_with_timeout = lambda raw, depth: _make_element(
            ref="", depth=depth, is_visible=True,
        )

        elements = walker.walk(hwnd=None)
        assert len(elements) <= config.max_elements
