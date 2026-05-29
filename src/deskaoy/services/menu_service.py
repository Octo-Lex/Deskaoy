"""MenuService — Start Menu + application menu bar interaction via UIA.

Windows equivalents of Peekaboo's macOS MenuService:
  - Start Menu search/list/click (instead of Apple menu bar)
  - Application menu bar traversal (File, Edit, etc.)

Implementation:
  - Uses UIA to walk the Start Menu tree when open
  - Searches via the search box (type text, read results)
  - App menu bars via UIA tree walk of the target window

HB-01: Only reads/drives existing UI — no window creation.
HB-02: Must work without admin privileges.
"""

from __future__ import annotations

import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MenuItem:
    """A menu item from Start Menu or application menu bar."""

    name: str
    path: str = ""  # Full path: "File > Recent > doc.txt"
    is_submenu: bool = False
    is_enabled: bool = True
    shortcut: str | None = None
    element: Any | None = field(default=None, repr=False, compare=False)


class MenuService:
    """Start Menu + application menu bar interaction via UIA.

    Usage::

        svc = MenuService()
        items = svc.list_start_items()
        svc.search_start("notepad")
        svc.click_start_item("Notepad")
        menu_items = svc.list_menu_bar(hwnd=12345)
        svc.click_menu_item(hwnd=12345, path="File > Save")
    """

    # Start Menu window class names (Windows 10/11)
    _START_CLASS_NAMES = (
        "Windows.UI.Core.CoreWindow",  # Windows 10 Start
        "StartMenu",                    # Alternative class name
    )

    # Start Menu search box automation IDs
    _SEARCH_BOX_IDS = ("SearchTextBox", "TextBox")

    def __init__(self, walker: Any = None) -> None:
        """Initialize MenuService.

        Args:
            walker: Optional UIAWalker instance. If None, created lazily.
        """
        self._walker = walker

    def _get_walker(self) -> Any:
        """Get or create UIAWalker."""
        if self._walker is None:
            from deskaoy.adapters.uia_walker import UIAWalker
            self._walker = UIAWalker()
        return self._walker

    def _get_uia(self) -> Any:
        """Get the IUIA singleton wrapper."""
        from deskaoy.adapters.uia_walker import _IUIAWrapper
        return _IUIAWrapper.get()

    # ================================================================
    # Start Menu
    # ================================================================

    def open_start_menu(self) -> bool:
        """Open the Windows Start Menu via keyboard shortcut.

        Returns:
            True if the Start key was sent successfully.
        """
        try:
            import pyautogui
            pyautogui.press("win")
            time.sleep(0.5)  # Wait for Start Menu animation
            return True
        except Exception as exc:
            logger.error("Failed to open Start Menu: %s", exc)
            return False

    def search_start(self, query: str) -> list[MenuItem]:
        """Search in the Start Menu by typing a query.

        Opens the Start Menu if not already open, types the query,
        and returns matching items from the search results.

        Args:
            query: Search text.

        Returns:
            List of MenuItem matching the search.
        """
        try:
            # Open Start Menu
            self.open_start_menu()
            time.sleep(0.3)

            # Type the search query
            import pyautogui
            pyautogui.write(query, interval=0.05)
            time.sleep(0.8)  # Wait for search results

            # Walk the Start Menu to find result items
            return self._walk_start_results(query)
        except Exception as exc:
            logger.error("Start Menu search failed: %s", exc)
            return []

    def list_start_items(self) -> list[MenuItem]:
        """List Start Menu pinned/all items.

        Opens the Start Menu and walks the UIA tree to find
        all interactive items.

        Returns:
            List of MenuItem for Start Menu entries.
        """
        try:
            self.open_start_menu()
            time.sleep(0.5)
            return self._walk_start_items()
        except Exception as exc:
            logger.error("Failed to list Start Menu items: %s", exc)
            return []

    def click_start_item(self, name: str) -> bool:
        """Click a Start Menu item by name.

        Searches the Start Menu for an item matching the given name
        and clicks it using UIA InvokePattern.

        Args:
            name: Name of the Start Menu item to click.

        Returns:
            True if the item was found and clicked.
        """
        try:
            self.open_start_menu()
            time.sleep(0.3)

            # Find the Start Menu window
            start_elem = self._find_start_menu_element()
            if start_elem is None:
                logger.warning("Start Menu window not found")
                return False

            # Search for the item by name
            uia = self._get_uia()
            condition = uia.iuia.CreatePropertyCondition(
                uia._uia_dll.UIA_NamePropertyId, name,
            )
            found = start_elem.FindFirst(uia.TREE_SCOPE_DESCENDANTS, condition)
            if found:
                # Try InvokePattern
                result = self._get_walker().try_invoke(found)
                if result and result.success:
                    return True
                # Fallback: click center of element
                rect = found.CurrentBoundingRectangle
                cx = (rect.left + rect.right) // 2
                cy = (rect.top + rect.bottom) // 2
                import pyautogui
                pyautogui.click(cx, cy)
                return True

            logger.warning("Start Menu item '%s' not found", name)
            return False
        except Exception as exc:
            logger.error("Failed to click Start Menu item '%s': %s", name, exc)
            return False

    # ================================================================
    # Application Menu Bar
    # ================================================================

    def list_menu_bar(self, hwnd: int) -> list[MenuItem]:
        """List application menu bar items (File, Edit, etc.).

        Walks the UIA tree of the given window looking for menu bar
        elements and their children.

        Args:
            hwnd: Window handle of the application.

        Returns:
            List of MenuItem for top-level menu entries.
        """
        items: list[MenuItem] = []
        try:
            uia = self._get_uia()
            root = uia.element_from_handle(hwnd)

            # Find menu bar element (control type 50012 = MenuBar)
            condition = uia.iuia.CreatePropertyCondition(
                uia._uia_dll.UIA_ControlTypePropertyId, 50012,
            )
            menubar = root.FindFirst(uia.TREE_SCOPE_DESCENDANTS, condition)
            if menubar is None:
                logger.debug("No menu bar found for HWND %s", hwnd)
                return items

            # Walk menu bar children
            items = self._walk_menu_items(menubar, depth=0, parent_path="")
        except Exception as exc:
            logger.error("Failed to list menu bar for HWND %s: %s", hwnd, exc)
        return items

    def click_menu_item(self, hwnd: int, path: str) -> bool:
        """Click a menu item by path (e.g., "File > Save").

        Traverses the menu bar hierarchy following the path segments,
        expanding submenus as needed, and clicks the final item.

        Args:
            hwnd: Window handle of the application.
            path: Menu path with " > " separator (e.g., "File > Save As").

        Returns:
            True if the menu item was found and clicked.
        """
        try:
            segments = [s.strip() for s in path.split(">")]
            if not segments:
                return False

            uia = self._get_uia()
            root = uia.element_from_handle(hwnd)

            # Find menu bar
            condition = uia.iuia.CreatePropertyCondition(
                uia._uia_dll.UIA_ControlTypePropertyId, 50012,
            )
            menubar = root.FindFirst(uia.TREE_SCOPE_DESCENDANTS, condition)
            if menubar is None:
                logger.warning("No menu bar found for HWND %s", hwnd)
                return False

            # Navigate path segments
            current = menubar
            for i, segment in enumerate(segments):
                is_last = i == len(segments) - 1

                # Find the item by name under current element
                name_condition = uia.iuia.CreatePropertyCondition(
                    uia._uia_dll.UIA_NamePropertyId, segment,
                )
                found = current.FindFirst(uia.TREE_SCOPE_CHILDREN, name_condition)

                if found is None:
                    # Try descendants instead of children
                    found = current.FindFirst(uia.TREE_SCOPE_DESCENDANTS, name_condition)

                if found is None:
                    logger.warning("Menu segment '%s' not found", segment)
                    return False

                if is_last:
                    # Click the final item
                    result = self._get_walker().try_invoke(found)
                    if result and result.success:
                        return True
                    # Fallback: click center
                    rect = found.CurrentBoundingRectangle
                    cx = (rect.left + rect.right) // 2
                    cy = (rect.top + rect.bottom) // 2
                    import pyautogui
                    pyautogui.click(cx, cy)
                    return True
                else:
                    # Expand submenu (if applicable)
                    expand_result = self._get_walker().try_expand(found)
                    if expand_result and expand_result.success:
                        time.sleep(0.2)  # Wait for submenu animation
                    current = found

            return False
        except Exception as exc:
            logger.error("Failed to click menu path '%s': %s", path, exc)
            return False

    # ================================================================
    # Internal helpers
    # ================================================================

    def _find_start_menu_element(self) -> Any:
        """Find the Start Menu window element via UIA root search."""
        try:
            uia = self._get_uia()
            root = uia.root

            # Search by class name
            for class_name in self._START_CLASS_NAMES:
                condition = uia.iuia.CreatePropertyCondition(
                    uia._uia_dll.UIA_ClassNamePropertyId, class_name,
                )
                found = root.FindFirst(uia.TREE_SCOPE_CHILDREN, condition)
                if found:
                    return found

            # Fallback: search by name "Start"
            name_condition = uia.iuia.CreatePropertyCondition(
                uia._uia_dll.UIA_NamePropertyId, "Start",
            )
            found = root.FindFirst(uia.TREE_SCOPE_CHILDREN, name_condition)
            return found
        except Exception as exc:
            logger.debug("Failed to find Start Menu element: %s", exc)
            return None

    def _walk_start_items(self) -> list[MenuItem]:
        """Walk the Start Menu tree and return items."""
        items: list[MenuItem] = []
        start_elem = self._find_start_menu_element()
        if start_elem is None:
            return items

        try:
            uia = self._get_uia()
            # Find all menu items (control type 50013 = MenuItem)
            # and buttons (50000) in the Start Menu
            for control_type_id in (50013, 50000, 50033):  # MenuItem, Button, SplitButton
                condition = uia.iuia.CreatePropertyCondition(
                    uia._uia_dll.UIA_ControlTypePropertyId, control_type_id,
                )
                # Use FindAll for all matches
                found_all = start_elem.FindAll(uia.TREE_SCOPE_DESCENDANTS, condition)
                if found_all:
                    for i in range(found_all.Length):
                        elem = found_all.GetElement(i)
                        try:
                            name = elem.CurrentName or ""
                            is_enabled = bool(elem.CurrentIsEnabled)
                            items.append(MenuItem(
                                name=name,
                                path=name,
                                is_submenu=False,
                                is_enabled=is_enabled,
                                element=elem,
                            ))
                        except Exception:
                            continue
        except Exception as exc:
            logger.debug("Failed to walk Start Menu items: %s", exc)
        return items

    def _walk_start_results(self, query: str) -> list[MenuItem]:
        """Walk the Start Menu search results."""
        items: list[MenuItem] = []
        start_elem = self._find_start_menu_element()
        if start_elem is None:
            return items

        try:
            uia = self._get_uia()
            # Find list items (control type 50007 = ListItem) in results
            condition = uia.iuia.CreatePropertyCondition(
                uia._uia_dll.UIA_ControlTypePropertyId, 50007,
            )
            found_all = start_elem.FindAll(uia.TREE_SCOPE_DESCENDANTS, condition)
            if found_all:
                for i in range(found_all.Length):
                    elem = found_all.GetElement(i)
                    try:
                        name = elem.CurrentName or ""
                        is_enabled = bool(elem.CurrentIsEnabled)
                        items.append(MenuItem(
                            name=name,
                            path=name,
                            is_submenu=False,
                            is_enabled=is_enabled,
                            element=elem,
                        ))
                    except Exception:
                        continue
        except Exception as exc:
            logger.debug("Failed to walk Start Menu results: %s", exc)
        return items

    def _walk_menu_items(
        self,
        parent: Any,
        depth: int,
        parent_path: str,
    ) -> list[MenuItem]:
        """Recursively walk menu items from a parent element."""
        items: list[MenuItem] = []
        try:
            uia = self._get_uia()
            walker = uia.control_walker

            child = walker.GetFirstChildElement(parent)
            while child is not None:
                try:
                    name = child.CurrentName or ""
                    control_type = child.CurrentControlType
                    is_enabled = bool(child.CurrentIsEnabled)

                    # Build path
                    path = f"{parent_path} > {name}" if parent_path else name

                    # Check if this is a menu item (50013) or button (50000)
                    if control_type in (50013, 50000, 50033):
                        is_submenu = control_type == 50013

                        # Try to get accelerator/shortcut
                        shortcut = ""
                        with contextlib.suppress(Exception):
                            shortcut = child.CurrentAcceleratorKey or ""

                        items.append(MenuItem(
                            name=name,
                            path=path,
                            is_submenu=is_submenu,
                            is_enabled=is_enabled,
                            shortcut=shortcut or None,
                            element=child,
                        ))

                        # Recurse into submenus (only one level deep to avoid explosion)
                        if is_submenu and depth < 1:
                            items.extend(
                                self._walk_menu_items(child, depth + 1, path)
                            )
                except Exception:
                    pass

                try:
                    child = walker.GetNextSiblingElement(child)
                except Exception:
                    break
        except Exception as exc:
            logger.debug("Menu walk failed: %s", exc)
        return items
