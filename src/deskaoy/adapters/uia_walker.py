"""Windows UI Automation tree walker — comtypes-based accessibility tree extraction.

Walks the Windows UI Automation tree starting from a window handle (HWND)
and produces structured elements compatible with the cascade engine:

  - AXNode instances (for AXSnapshot -> Tier 1 selector resolution)
  - Detection instances (for GroundingPipeline -> visual-structural fusion)

Architecture:
  - Uses comtypes to access IUIAutomation COM interfaces directly
  - Singleton IUIA wrapper (like pywinauto's pattern) for efficiency
  - Threaded extraction with per-element timeout (from pywinauto-mcp)
  - Filters by control type, visibility, and bounds validity

Reference implementations studied:
  - pywinauto: pywinauto/windows/uia_element_info.py (COM wrapping)
  - pywinauto: pywinauto/windows/uia_defines.py (IUIA singleton)
  - pywinauto-mcp: desktop_state/walker.py (tree walking with timeout)

This module has ZERO dependency on pywinauto, pyautogui, or Patchright.
Only requires: comtypes (Windows COM interop, pure Python + C wrapper).
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from deskaoy.cascade.types import AXNode, AXSnapshot
from deskaoy.grounding.types import BBox, Detection, DetectionSource, ElementRole

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# UIA Pattern IDs (Windows UI Automation)
# ---------------------------------------------------------------------------

UIA_INVOKE_PATTERN_ID = 10000
UIA_VALUE_PATTERN_ID = 10002
UIA_TOGGLE_PATTERN_ID = 10004
UIA_EXPAND_COLLAPSE_PATTERN_ID = 10005
UIA_SELECTION_ITEM_PATTERN_ID = 10010
UIA_SCROLL_ITEM_PATTERN_ID = 10017


# ---------------------------------------------------------------------------
# Control type mapping: Windows UIA numeric IDs -> our types
# ---------------------------------------------------------------------------

# UIA control type IDs -> ElementRole
_UIA_CONTROL_TYPE_MAP: dict[int, ElementRole] = {
    50000: ElementRole.BUTTON,
    50001: ElementRole.OTHER,         # UIA_CalendarControlTypeId
    50004: ElementRole.INPUT,
    50005: ElementRole.LINK,
    50002: ElementRole.CHECKBOX,
    50015: ElementRole.RADIO,
    50003: ElementRole.DROPDOWN,
    50020: ElementRole.TAB,
    50017: ElementRole.SLIDER,
    50013: ElementRole.MENU_ITEM,
    50006: ElementRole.IMAGE,         # UIA_ImageControlTypeId
    50007: ElementRole.CONTAINER,
    50010: ElementRole.LINK,          # UIA_LinkControlTypeId
    50022: ElementRole.TEXT,
    50016: ElementRole.CONTAINER,
    50028: ElementRole.CONTAINER,
    50029: ElementRole.CONTAINER,
    50030: ElementRole.CONTAINER,
    50008: ElementRole.CONTAINER,
    50033: ElementRole.CONTAINER,
    50032: ElementRole.CONTAINER,
    50011: ElementRole.CONTAINER,
    50012: ElementRole.CONTAINER,
    50031: ElementRole.CONTAINER,
    50021: ElementRole.CONTAINER,
    50009: ElementRole.CONTAINER,
    50024: ElementRole.CONTAINER,
    50025: ElementRole.CONTAINER,
    50034: ElementRole.CONTAINER,
    50014: ElementRole.OTHER,
    50018: ElementRole.INPUT,
    50019: ElementRole.CONTAINER,
    50023: ElementRole.OTHER,
    50026: ElementRole.CONTAINER,
    50027: ElementRole.CONTAINER,
    50035: ElementRole.CONTAINER,
    50036: ElementRole.OTHER,
    50037: ElementRole.OTHER,
}

# UIA control type IDs -> role string for AXNode
_UIA_CONTROL_TYPE_NAMES: dict[int, str] = {
    50000: "button",
    50001: "calendar",
    50002: "checkbox",
    50003: "combobox",
    50004: "edit",
    50005: "hyperlink",
    50006: "image",
    50007: "listitem",
    50008: "group",
    50009: "header",
    50010: "link",
    50011: "menu",
    50012: "menubar",
    50013: "menuitem",
    50014: "progressbar",
    50015: "radio",
    50016: "scrollbar",
    50017: "slider",
    50018: "spinner",
    50019: "tab",
    50020: "tabitem",
    50021: "table",
    50022: "text",
    50023: "thumb",
    50024: "titlebar",
    50025: "toolbar",
    50026: "tree",
    50027: "treeitem",
    50028: "datagrid",
    50029: "dataitem",
    50030: "document",
    50031: "pane",
    50032: "window",
    50033: "splitbutton",
    50034: "statusbar",
    50035: "group",
    50036: "tip",
    50037: "semanticzoom",
}

# Interactive control type IDs for filtering
_INTERACTIVE_TYPE_IDS: frozenset[int] = frozenset({
    50000,  # Button
    50002,  # CheckBox
    50003,  # ComboBox
    50004,  # Edit
    50005,  # Hyperlink
    50007,  # ListItem
    50010,  # Link
    50013,  # MenuItem
    50015,  # RadioButton
    50017,  # Slider
    50018,  # Spinner
    50020,  # TabItem
    50033,  # SplitButton
})

# Informative (but not interactive) control types
_INFORMATIVE_TYPE_IDS: frozenset[int] = frozenset({
    50022,  # Text
    50024,  # TitleBar
    50025,  # ToolBar
    50034,  # StatusBar
    50009,  # Header
    50014,  # ProgressBar
})


# ---------------------------------------------------------------------------
# IUIA singleton — lazy COM initialization
# ---------------------------------------------------------------------------

class _IUIAWrapper:
    """Singleton wrapper for IUIAutomation COM interfaces.

    Pattern from pywinauto's uia_defines.IUIA but simplified.
    Lazily initializes COM on first use. Thread-safe via module-level lock.
    """

    _instance: _IUIAWrapper | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize COM interfaces. Called once by get()."""
        import comtypes
        import comtypes.client

        # Load UIAutomationCore type library
        self._uia_dll = comtypes.client.GetModule("UIAutomationCore.dll")
        self._client = comtypes.gen.UIAutomationClient

        # Create IUIAutomation instance
        clsid = self._client.CUIAutomation().IPersist_GetClassID()
        self.iuia = comtypes.CoCreateInstance(
            clsid,
            interface=self._client.IUIAutomation,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
        )

        # Pre-built conditions
        self.true_condition = self.iuia.CreateTrueCondition()

        # Tree scope constants
        self.TREE_SCOPE_CHILDREN = self._uia_dll.TreeScope_Children
        self.TREE_SCOPE_DESCENDANTS = self._uia_dll.TreeScope_Descendants
        self.TREE_SCOPE_ELEMENT = self._uia_dll.TreeScope_Element

        # Control view walker (excludes raw structural elements)
        self.control_walker = self.iuia.ControlViewWalker

        # Raw view walker (everything)
        self.raw_walker = self.iuia.RawViewWalker

        # Root element
        self.root = self.iuia.GetRootElement()

        # Build control type name lookup from DLL
        self._control_type_names: dict[int, str] = {}
        prefix = "UIA_"
        suffix = "ControlTypeId"
        for attr in dir(self._uia_dll):
            if attr.startswith(prefix) and attr.endswith(suffix):
                name = attr[len(prefix):-len(suffix)]
                type_id = getattr(self._uia_dll, attr)
                self._control_type_names[type_id] = name.lower()

    @classmethod
    def get(cls) -> _IUIAWrapper:
        """Get or create the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        with cls._lock:
            cls._instance = None

    def element_from_handle(self, hwnd: int) -> Any:
        """Get IUIAutomationElement from a window handle."""
        return self.iuia.ElementFromHandle(hwnd)

    def element_from_point(self, x: int, y: int) -> Any:
        """Get element at screen coordinates."""
        from ctypes.wintypes import tagPOINT
        return self.iuia.ElementFromPoint(tagPOINT(x, y))

    def get_focused_element(self) -> Any:
        """Get the currently focused element."""
        return self.iuia.GetFocusedElement()

    def control_type_name(self, type_id: int) -> str:
        """Convert numeric control type ID to human-readable name."""
        return self._control_type_names.get(type_id, f"unknown_{type_id}")


# ---------------------------------------------------------------------------
# Element extraction result
# ---------------------------------------------------------------------------

@dataclass
class UIAElement:
    """Extracted UI Automation element with all properties we care about.

    Compatible with both AXNode (cascade selector tier) and Detection
    (grounding pipeline structural source).
    """

    ref: str                                          # Sequential ID (e.g., "e0", "e1")
    name: str                                         # CurrentName
    control_type: str                                 # "button", "edit", etc.
    control_type_id: int                              # Numeric UIA control type
    automation_id: str                                # CurrentAutomationId
    class_name: str                                   # CurrentClassName
    bounds: tuple[float, float, float, float]         # (left, top, width, height)
    is_enabled: bool
    is_visible: bool
    is_interactive: bool
    is_offscreen: bool
    process_id: int
    value: str                                        # From ValuePattern
    help_text: str                                    # CurrentHelpText
    accelerator: str                                  # CurrentAcceleratorKey
    depth: int                                        # Tree depth

    @property
    def bbox(self) -> BBox:
        """Get a BBox for grounding fusion."""
        left, top, w, h = self.bounds
        return BBox(x1=left, y1=top, x2=left + w, y2=top + h)

    @property
    def center(self) -> tuple[float, float]:
        """Get center point of element."""
        left, top, w, h = self.bounds
        return (left + w / 2, top + h / 2)

    @property
    def element_role(self) -> ElementRole:
        """Map to our ElementRole enum."""
        return _UIA_CONTROL_TYPE_MAP.get(self.control_type_id, ElementRole.OTHER)

    def to_ax_node(self) -> AXNode:
        """Convert to AXNode for the cascade selector tier."""
        return AXNode(
            ref=self.ref,
            role=self.control_type,
            name=self.name,
            value=self.value or None,
            description=self.help_text or None,
            bounds=self.bounds,
            focused=False,
            disabled=not self.is_enabled,
        )

    def to_detection(self) -> Detection:
        """Convert to Detection for grounding pipeline structural source."""
        return Detection(
            bbox=self.bbox,
            confidence=0.95,  # Structural confidence floor
            label=self.name or self.control_type,
            role=self.element_role,
            source=DetectionSource.STRUCTURAL,
            text=self.name or None,
        )


# ---------------------------------------------------------------------------
# Walker configuration
# ---------------------------------------------------------------------------

@dataclass
class WalkerConfig:
    """Configuration for the UIA tree walker."""

    max_depth: int = 8
    """Maximum tree depth to walk from the root element."""

    element_timeout_s: float = 0.3
    """Per-element property extraction timeout in seconds."""

    include_invisible: bool = False
    """Include offscreen/invisible elements."""

    include_non_interactive: bool = True
    """Include informative elements (Text, StatusBar, etc.)."""

    min_element_size: int = 2
    """Minimum width/height in pixels for an element to be included."""

    use_raw_walker: bool = False
    """Use RawViewWalker instead of ControlViewWalker."""

    max_elements: int = 500
    """Hard cap on total elements to prevent runaway walks."""


# ---------------------------------------------------------------------------
# The walker
# ---------------------------------------------------------------------------

class UIAWalker:
    """Walk the Windows UI Automation tree and extract elements.

    Inspired by pywinauto-mcp's UIElementWalker but redesigned to:
      1. Work directly with comtypes (no pywinauto dependency)
      2. Produce typed UIAElement objects (not dicts)
      3. Integrate with both AXSnapshot and GroundingPipeline
      4. Use per-element threading timeout (from pywinauto-mcp)
      5. Support both ControlViewWalker and RawViewWalker

    Usage::

        walker = UIAWalker()
        elements = walker.walk(hwnd=some_window_handle)
        snapshot = walker.walk_to_snapshot(hwnd=some_window_handle)
    """

    def __init__(self, config: WalkerConfig | None = None) -> None:
        self._config = config or WalkerConfig()
        self._uia: _IUIAWrapper | None = None

    def _get_uia(self) -> _IUIAWrapper:
        """Lazily initialize the IUIA singleton."""
        if self._uia is None:
            self._uia = _IUIAWrapper.get()
        return self._uia

    # =================================================================
    # Public API
    # =================================================================

    def walk(self, hwnd: int | None = None) -> list[UIAElement]:
        """Walk the UI Automation tree and return extracted elements.

        Args:
            hwnd: Window handle to start from. If None, walks from root
                  (entire desktop - very slow, use sparingly).

        Returns:
            List of UIAElement instances, depth-first order.
        """
        uia = self._get_uia()

        if hwnd is not None:
            try:
                root = uia.element_from_handle(hwnd)
            except Exception as exc:
                logger.error("Failed to get element for HWND %s: %s", hwnd, exc)
                return []
        else:
            root = uia.root

        elements: list[UIAElement] = []
        self._walk_recursive(root, depth=0, elements=elements)
        return elements

    def walk_to_snapshot(
        self,
        hwnd: int | None = None,
        url: str = "",
        title: str = "",
    ) -> AXSnapshot:
        """Walk the UIA tree and return an AXSnapshot.

        Convenience method that converts elements to AXNodes directly.
        """
        start = time.monotonic()
        elements = self.walk(hwnd=hwnd)

        nodes: dict[str, AXNode] = {}
        for elem in elements:
            nodes[elem.ref] = elem.to_ax_node()

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "UIA walk completed: %d elements in %.0fms",
            len(elements),
            elapsed_ms,
        )

        return AXSnapshot(
            url=url,
            title=title,
            nodes=nodes,
        )

    def walk_to_detections(self, hwnd: int | None = None) -> list[Detection]:
        """Walk the UIA tree and return Detection instances.

        For feeding into the GroundingPipeline's structural source.
        """
        elements = self.walk(hwnd=hwnd)
        return [elem.to_detection() for elem in elements]

    def find_element_at_point(self, x: int, y: int) -> UIAElement | None:
        """Find the UIA element at a specific screen coordinate.

        Uses IUIAutomation::ElementFromPoint for O(1) lookup.
        """
        uia = self._get_uia()
        try:
            raw_elem = uia.element_from_point(x, y)
            return self._extract_element(raw_elem, ref="point", depth=0)
        except Exception as exc:
            logger.debug("ElementFromPoint(%d, %d) failed: %s", x, y, exc)
            return None

    def find_element_by_name(
        self,
        hwnd: int,
        name: str,
    ) -> UIAElement | None:
        """Find an interactive element by its Name property.

        Searches descendants of the given window. Returns the first match
        or None if not found.
        """
        uia = self._get_uia()
        try:
            root = uia.element_from_handle(hwnd)
            condition = uia.iuia.CreatePropertyCondition(
                uia._uia_dll.UIA_NamePropertyId,
                name,
            )
            found = root.FindFirst(uia.TREE_SCOPE_DESCENDANTS, condition)
            if found:
                return self._extract_element(found, ref="name_search", depth=0)
        except Exception as exc:
            logger.debug("FindElement by name failed: %s", exc)
        return None

    def find_element_by_automation_id(
        self,
        hwnd: int,
        automation_id: str,
    ) -> UIAElement | None:
        """Find an element by its AutomationId property.

        Uses UIA condition-based search for efficiency.
        """
        uia = self._get_uia()
        try:
            root = uia.element_from_handle(hwnd)
            condition = uia.iuia.CreatePropertyCondition(
                uia._uia_dll.UIA_AutomationIdPropertyId,
                automation_id,
            )
            found = root.FindFirst(uia.TREE_SCOPE_DESCENDANTS, condition)
            if found:
                return self._extract_element(found, ref="auto_id", depth=0)
        except Exception as exc:
            logger.debug("FindElement by automation_id failed: %s", exc)
        return None

    def get_focused_element(self, hwnd: int | None = None) -> UIAElement | None:
        """Get the currently focused UIA element, optionally within a window."""
        uia = self._get_uia()
        try:
            raw = uia.get_focused_element()
            if raw is not None:
                return self._extract_element(raw, ref="focused", depth=0)
        except Exception as exc:
            logger.debug("GetFocusedElement failed: %s", exc)
        return None

    def find_element_by_element_id(
        self,
        hwnd: int,
        element_id: str,
    ) -> UIAElement | None:
        """Resolve a snapshot element ID (E1, T2, B3) to a UIA element.

        Uses the deterministic element ordering from assign_element_ids()
        to find the Nth element matching the role prefix.

        Args:
            hwnd: Window handle to search within.
            element_id: Snapshot element ID like "B1", "T3", "E5".

        Returns:
            UIAElement if found, or None.
        """
        from deskaoy.cascade.snapshot_types import (
            ROLE_ALIASES,
            ROLE_PREFIXES,
            validate_element_id,
        )

        # Validate format
        if not validate_element_id(element_id):
            logger.debug("Invalid element ID format: %s", element_id)
            return None

        # Parse prefix and number
        prefix = element_id[0]
        try:
            index = int(element_id[1:])
        except ValueError:
            logger.debug("Invalid element ID number: %s", element_id)
            return None

        if index < 1:
            logger.debug("Element ID index must be >= 1: %s", element_id)
            return None

        # Map prefix to UIA control type IDs
        # Build reverse map: prefix -> set of control type IDs
        prefix_to_type_ids = self._build_prefix_to_type_ids(
            ROLE_PREFIXES, ROLE_ALIASES,
        )

        target_type_ids = prefix_to_type_ids.get(prefix)
        if target_type_ids is None:
            # E prefix matches any role (generic)
            target_type_ids = None

        # Walk tree and filter by role, return Nth match
        elements = self.walk(hwnd=hwnd)
        match_count = 0
        for elem in elements:
            if target_type_ids is not None:
                # Check if the element's control type maps to this prefix
                elem_prefix = self._get_element_prefix(
                    elem.control_type, ROLE_PREFIXES, ROLE_ALIASES,
                )
                if elem_prefix != prefix:
                    continue
            # For E prefix (generic), all elements match
            match_count += 1
            if match_count == index:
                return elem

        logger.debug(
            "Element ID %s not found (matched %d of %d elements)",
            element_id, match_count, len(elements),
        )
        return None

    def _build_prefix_to_type_ids(
        self,
        role_prefixes: dict[str, str],
        role_aliases: dict[str, str],
    ) -> dict[str, set[int]]:
        """Build reverse map: prefix -> set of UIA control type IDs."""
        # Build role -> prefix (with alias resolution)
        result: dict[str, set[int]] = {}
        for _role, prefix in role_prefixes.items():
            if prefix not in result:
                result[prefix] = set()

        # Map UIA control type names back to prefixes
        for type_id, type_name in _UIA_CONTROL_TYPE_NAMES.items():
            # Resolve through aliases
            canonical = role_aliases.get(type_name, type_name)
            prefix = role_prefixes.get(canonical)
            if prefix and prefix in result:
                result[prefix].add(type_id)

        return result

    def _get_element_prefix(
        self,
        control_type: str,
        role_prefixes: dict[str, str],
        role_aliases: dict[str, str],
    ) -> str:
        """Get the prefix for an element's control type."""
        canonical = role_aliases.get(control_type, control_type)
        return role_prefixes.get(canonical, "E")

    # =================================================================
    # Pattern-based actions (BATCH-25: Action-First)
    # =================================================================

    def try_invoke(self, raw_element: Any) -> PatternActionResult | None:
        """Try to invoke (click) an element via InvokePattern."""
        return _try_invoke_pattern(raw_element)

    def try_set_value(self, raw_element: Any, value: str) -> PatternActionResult | None:
        """Try to set a value via ValuePattern."""
        return _try_set_value_pattern(raw_element, value)

    def try_get_value(self, raw_element: Any) -> str | None:
        """Try to get current value via ValuePattern."""
        return _try_get_value_pattern(raw_element)

    def try_toggle(self, raw_element: Any) -> PatternActionResult | None:
        """Try to toggle an element via TogglePattern."""
        return _try_toggle_pattern(raw_element)

    def try_expand(self, raw_element: Any) -> PatternActionResult | None:
        """Try to expand an element via ExpandCollapsePattern."""
        return _try_expand_pattern(raw_element)

    def try_collapse(self, raw_element: Any) -> PatternActionResult | None:
        """Try to collapse an element via ExpandCollapsePattern."""
        return _try_collapse_pattern(raw_element)

    def try_select(self, raw_element: Any) -> PatternActionResult | None:
        """Try to select an element via SelectionItemPattern."""
        return _try_select_pattern(raw_element)

    def try_scroll_into_view(self, raw_element: Any) -> PatternActionResult | None:
        """Try to scroll an element into view via ScrollItemPattern."""
        return _try_scroll_into_view_pattern(raw_element)

    def invoke_action(
        self,
        raw_element: Any,
        action: str,
        value: str = "",
    ) -> PatternActionResult | None:
        """Dispatch a UIA pattern action on a raw element.

        Central dispatcher that maps action names to pattern helpers.
        Returns PatternActionResult if the pattern was available and
        executed, or None if the pattern is not supported on this element.
        """
        dispatch = {
            "click": lambda: _try_invoke_pattern(raw_element),
            "invoke": lambda: _try_invoke_pattern(raw_element),
            "toggle": lambda: _try_toggle_pattern(raw_element),
            "expand": lambda: _try_expand_pattern(raw_element),
            "collapse": lambda: _try_collapse_pattern(raw_element),
            "select": lambda: _try_select_pattern(raw_element),
            "scroll_into_view": lambda: _try_scroll_into_view_pattern(raw_element),
            "set_value": lambda: _try_set_value_pattern(raw_element, value),
        }
        handler = dispatch.get(action)
        if handler:
            return handler()
        return None

    # =================================================================
    # Recursive tree walking
    # =================================================================

    def _walk_recursive(
        self,
        element: Any,
        depth: int,
        elements: list[UIAElement],
    ) -> None:
        """Recursively walk the UI Automation tree."""
        config = self._config

        # Hard caps
        if depth > config.max_depth:
            return
        if len(elements) >= config.max_elements:
            return

        # Get the tree walker
        uia = self._get_uia()
        walker = uia.raw_walker if config.use_raw_walker else uia.control_walker

        try:
            child = walker.GetFirstChildElement(element)
        except Exception:
            return

        while child is not None:
            if len(elements) >= config.max_elements:
                return

            # Extract element properties with timeout
            uia_elem = self._extract_with_timeout(child, depth)

            if uia_elem is not None and self._should_include(uia_elem):
                uia_elem.ref = f"e{len(elements)}"
                elements.append(uia_elem)

                # Recurse into children
                self._walk_recursive(child, depth + 1, elements)

            # Move to next sibling
            try:
                child = walker.GetNextSiblingElement(child)
            except Exception:
                break

    def _extract_with_timeout(
        self,
        raw_element: Any,
        depth: int,
    ) -> UIAElement | None:
        """Extract element properties in a thread with timeout.

        Some COM elements hang forever when accessing properties
        (dead processes, etc.). Pattern from pywinauto-mcp.
        """
        config = self._config
        result: list[UIAElement | None] = [None]

        def _extract() -> None:
            try:
                elem = self._extract_element(raw_element, ref="", depth=depth)
                result[0] = elem
            except Exception:
                pass

        thread = threading.Thread(target=_extract, daemon=True)
        thread.start()
        thread.join(timeout=config.element_timeout_s)

        return result[0]

    def _extract_element(
        self,
        raw: Any,
        ref: str,
        depth: int,
    ) -> UIAElement | None:
        """Extract all properties from a raw IUIAutomationElement."""
        try:
            # Core properties (all fast COM calls)
            name = raw.CurrentName or ""
            control_type_id = raw.CurrentControlType
            automation_id = raw.CurrentAutomationId or ""
            class_name = raw.CurrentClassName or ""
            is_enabled = bool(raw.CurrentIsEnabled)
            is_offscreen = bool(raw.CurrentIsOffscreen)
            process_id = raw.CurrentProcessId

            # Bounding rectangle
            try:
                rect = raw.CurrentBoundingRectangle
                bounds = (
                    float(rect.left),
                    float(rect.top),
                    float(rect.right - rect.left),
                    float(rect.bottom - rect.top),
                )
            except Exception:
                return None  # No bounds = skip

            # Value pattern (optional)
            value = ""
            with contextlib.suppress(Exception):
                value = _get_value_pattern(raw) or ""

            # Help text
            help_text = ""
            with contextlib.suppress(Exception):
                help_text = raw.CurrentHelpText or ""

            # Accelerator key
            accelerator = ""
            with contextlib.suppress(Exception):
                accelerator = raw.CurrentAcceleratorKey or ""

            # Map control type
            control_type = _UIA_CONTROL_TYPE_NAMES.get(
                control_type_id,
                f"unknown_{control_type_id}",
            )

            # Derive flags
            is_visible = not is_offscreen
            is_interactive = control_type_id in _INTERACTIVE_TYPE_IDS

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

        except Exception as exc:
            logger.debug("Failed to extract UIA element: %s", exc)
            return None

    def _should_include(self, elem: UIAElement) -> bool:
        """Filter elements based on configuration."""
        config = self._config

        if not config.include_invisible and not elem.is_visible:
            return False

        _, _, w, h = elem.bounds
        if w < config.min_element_size or h < config.min_element_size:
            return False

        return not (not config.include_non_interactive and not elem.is_interactive)


# ---------------------------------------------------------------------------
# Pattern action result
# ---------------------------------------------------------------------------

@dataclass
class PatternActionResult:
    """Result of a UIA pattern-based action."""
    success: bool
    pattern_used: str           # "InvokePattern", "ValuePattern", etc.
    fallback_used: bool        # True if fell back to pyautogui
    element_id: str | None  # Snapshot element ID if resolved
    error: str | None = None


# ---------------------------------------------------------------------------
# Pattern helpers
# ---------------------------------------------------------------------------

def _get_value_pattern(raw_element: Any) -> str | None:
    """Extract CurrentValue from ValuePattern, or None if unsupported."""
    try:
        pattern = raw_element.GetCurrentPattern(UIA_VALUE_PATTERN_ID)
        if pattern:
            from comtypes.gen.UIAutomationClient import IUIAutomationValuePattern
            iface = pattern.QueryInterface(IUIAutomationValuePattern)
            val = iface.CurrentValue
            return val if val else None
    except Exception:
        return None


def _try_invoke_pattern(raw_element: Any) -> PatternActionResult | None:
    """Try to invoke an element using InvokePattern."""
    try:
        pattern = raw_element.GetCurrentPattern(UIA_INVOKE_PATTERN_ID)
        if pattern:
            from comtypes.gen.UIAutomationClient import IUIAutomationInvokePattern
            iface = pattern.QueryInterface(IUIAutomationInvokePattern)
            iface.Invoke()
            return PatternActionResult(
                success=True,
                pattern_used="InvokePattern",
                fallback_used=False,
                element_id=None,
            )
    except Exception as exc:
        logger.debug("InvokePattern failed: %s", exc)
    return None


def _try_set_value_pattern(raw_element: Any, value: str) -> PatternActionResult | None:
    """Try to set a value using ValuePattern."""
    try:
        pattern = raw_element.GetCurrentPattern(UIA_VALUE_PATTERN_ID)
        if pattern:
            from comtypes.gen.UIAutomationClient import IUIAutomationValuePattern
            iface = pattern.QueryInterface(IUIAutomationValuePattern)
            iface.SetValue(value)
            return PatternActionResult(
                success=True,
                pattern_used="ValuePattern",
                fallback_used=False,
                element_id=None,
            )
    except Exception as exc:
        logger.debug("ValuePattern.SetValue failed: %s", exc)
    return None


def _try_get_value_pattern(raw_element: Any) -> str | None:
    """Try to get current value using ValuePattern."""
    return _get_value_pattern(raw_element)


def _try_toggle_pattern(raw_element: Any) -> PatternActionResult | None:
    """Try to toggle an element using TogglePattern."""
    try:
        pattern = raw_element.GetCurrentPattern(UIA_TOGGLE_PATTERN_ID)
        if pattern:
            from comtypes.gen.UIAutomationClient import IUIAutomationTogglePattern
            iface = pattern.QueryInterface(IUIAutomationTogglePattern)
            iface.Toggle()
            return PatternActionResult(
                success=True,
                pattern_used="TogglePattern",
                fallback_used=False,
                element_id=None,
            )
    except Exception as exc:
        logger.debug("TogglePattern failed: %s", exc)
    return None


def _try_expand_pattern(raw_element: Any) -> PatternActionResult | None:
    """Try to expand an element using ExpandCollapsePattern."""
    try:
        pattern = raw_element.GetCurrentPattern(UIA_EXPAND_COLLAPSE_PATTERN_ID)
        if pattern:
            from comtypes.gen.UIAutomationClient import IUIAutomationExpandCollapsePattern
            iface = pattern.QueryInterface(IUIAutomationExpandCollapsePattern)
            iface.Expand()
            return PatternActionResult(
                success=True,
                pattern_used="ExpandCollapsePattern",
                fallback_used=False,
                element_id=None,
            )
    except Exception as exc:
        logger.debug("ExpandCollapsePattern.Expand failed: %s", exc)
    return None


def _try_collapse_pattern(raw_element: Any) -> PatternActionResult | None:
    """Try to collapse an element using ExpandCollapsePattern."""
    try:
        pattern = raw_element.GetCurrentPattern(UIA_EXPAND_COLLAPSE_PATTERN_ID)
        if pattern:
            from comtypes.gen.UIAutomationClient import IUIAutomationExpandCollapsePattern
            iface = pattern.QueryInterface(IUIAutomationExpandCollapsePattern)
            iface.Collapse()
            return PatternActionResult(
                success=True,
                pattern_used="ExpandCollapsePattern",
                fallback_used=False,
                element_id=None,
            )
    except Exception as exc:
        logger.debug("ExpandCollapsePattern.Collapse failed: %s", exc)
    return None


def _try_select_pattern(raw_element: Any) -> PatternActionResult | None:
    """Try to select an element using SelectionItemPattern."""
    try:
        pattern = raw_element.GetCurrentPattern(UIA_SELECTION_ITEM_PATTERN_ID)
        if pattern:
            from comtypes.gen.UIAutomationClient import IUIAutomationSelectionItemPattern
            iface = pattern.QueryInterface(IUIAutomationSelectionItemPattern)
            iface.Select()
            return PatternActionResult(
                success=True,
                pattern_used="SelectionItemPattern",
                fallback_used=False,
                element_id=None,
            )
    except Exception as exc:
        logger.debug("SelectionItemPattern failed: %s", exc)
    return None


def _try_scroll_into_view_pattern(raw_element: Any) -> PatternActionResult | None:
    """Try to scroll an element into view using ScrollItemPattern."""
    try:
        pattern = raw_element.GetCurrentPattern(UIA_SCROLL_ITEM_PATTERN_ID)
        if pattern:
            from comtypes.gen.UIAutomationClient import IUIAutomationScrollItemPattern
            iface = pattern.QueryInterface(IUIAutomationScrollItemPattern)
            iface.ScrollIntoView()
            return PatternActionResult(
                success=True,
                pattern_used="ScrollItemPattern",
                fallback_used=False,
                element_id=None,
            )
    except Exception as exc:
        logger.debug("ScrollItemPattern failed: %s", exc)
    return None
