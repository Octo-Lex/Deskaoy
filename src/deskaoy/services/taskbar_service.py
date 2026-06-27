"""TaskbarService — Taskbar and System Tray interaction via UIA.

Windows equivalents of Peekaboo's macOS DockService:
  - Taskbar running apps (instead of Dock icons)
  - System tray icons (instead of menu bar extras)

Implementation:
  - Taskbar is Shell_TrayWnd class
  - Running apps: MSTaskListWClass with button elements
  - System tray: ToolbarWindow32 in NotifyIconOverflowWindow

HB-01: Only reads/drives existing UI — no window creation.
HB-02: Must work without admin privileges.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TaskbarItem:
    """A taskbar button or system tray icon."""

    name: str
    app_id: str | None = None
    is_running: bool = True
    is_pinned: bool = False
    tooltip: str | None = None
    element: Any | None = field(default=None, repr=False, compare=False)


class TaskbarService:
    """Taskbar and System Tray interaction via UIA.

    Usage::

        svc = TaskbarService()
        apps = svc.list_running_apps()
        svc.click_taskbar_button("Chrome")
        tray = svc.list_tray_icons()
        svc.click_tray_icon("Volume")
        state = svc.get_taskbar_state()
    """

    # Taskbar class names
    _TASKBAR_CLASS = "Shell_TrayWnd"
    _TASKLIST_CLASS = "MSTaskListWClass"
    _TRAY_CLASS = "ToolbarWindow32"
    _TRAY_OVERFLOW_CLASS = "NotifyIconOverflowWindow"

    def __init__(self, walker: Any = None) -> None:
        """Initialize TaskbarService.

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
    # Taskbar buttons
    # ================================================================

    def list_running_apps(self) -> list[TaskbarItem]:
        """List taskbar buttons for running applications.

        Walks the taskbar's MSTaskListWClass to find buttons
        representing running and pinned applications.

        Returns:
            List of TaskbarItem for each taskbar button.
        """
        items: list[TaskbarItem] = []
        try:
            uia = self._get_uia()
            root = uia.root

            # Find taskbar window
            taskbar = self._find_taskbar_element(root)
            if taskbar is None:
                logger.warning("Taskbar window not found")
                return items

            # Find MSTaskListWClass
            tasklist = self._find_child_by_class(taskbar, self._TASKLIST_CLASS)
            if tasklist is None:
                logger.debug("MSTaskListWClass not found in taskbar")
                return items

            # Walk buttons in the task list
            items = self._walk_taskbar_buttons(tasklist)
        except Exception as exc:
            logger.error("Failed to list running apps: %s", exc)
        return items

    def click_taskbar_button(self, name: str) -> bool:
        """Click a taskbar button by application name.

        Args:
            name: Application name to match (case-insensitive contains).

        Returns:
            True if the button was found and clicked.
        """
        try:
            items = self.list_running_apps()
            for item in items:
                if name.lower() in item.name.lower() and item.element is not None:
                    result = self._get_walker().try_invoke(item.element)
                    if result and result.success:
                        return True
                    # Fallback: click center of element
                    rect = item.element.CurrentBoundingRectangle
                    cx = (rect.left + rect.right) // 2
                    cy = (rect.top + rect.bottom) // 2
                    import pyautogui
                    pyautogui.click(cx, cy)
                    return True

            logger.warning("Taskbar button '%s' not found", name)
            return False
        except Exception as exc:
            logger.error("Failed to click taskbar button '%s': %s", name, exc)
            return False

    def right_click_taskbar(self, name: str) -> bool:
        """Right-click a taskbar button by application name.

        Args:
            name: Application name to match.

        Returns:
            True if the button was found and right-clicked.
        """
        try:
            items = self.list_running_apps()
            for item in items:
                if name.lower() in item.name.lower() and item.element is not None:
                    rect = item.element.CurrentBoundingRectangle
                    cx = (rect.left + rect.right) // 2
                    cy = (rect.top + rect.bottom) // 2
                    import pyautogui
                    pyautogui.rightClick(cx, cy)
                    return True

            logger.warning("Taskbar button '%s' not found for right-click", name)
            return False
        except Exception as exc:
            logger.error("Failed to right-click taskbar button '%s': %s", name, exc)
            return False

    # ================================================================
    # System tray
    # ================================================================

    def list_tray_icons(self) -> list[TaskbarItem]:
        """List system tray (notification area) icons.

        Walks the ToolbarWindow32 in the notification area to
        enumerate tray icons.

        Returns:
            List of TaskbarItem for each tray icon.
        """
        items: list[TaskbarItem] = []
        try:
            uia = self._get_uia()
            root = uia.root

            # Find the taskbar first
            taskbar = self._find_taskbar_element(root)
            if taskbar is None:
                return items

            # Find tray area (ToolbarWindow32 within taskbar)
            tray = self._find_child_by_class(taskbar, self._TRAY_CLASS)
            if tray is not None:
                items.extend(self._walk_tray_buttons(tray))

            # Also check overflow area (hidden icons)
            overflow = self._find_overflow_tray(root)
            if overflow is not None:
                items.extend(self._walk_tray_buttons(overflow))

        except Exception as exc:
            logger.error("Failed to list tray icons: %s", exc)
        return items

    def click_tray_icon(self, name: str) -> bool:
        """Click a system tray icon by name.

        Args:
            name: Tray icon name/tooltip to match.

        Returns:
            True if the icon was found and clicked.
        """
        try:
            icons = self.list_tray_icons()
            for icon in icons:
                if name.lower() in icon.name.lower() and icon.element is not None:
                    result = self._get_walker().try_invoke(icon.element)
                    if result and result.success:
                        return True
                    # Fallback: click center
                    rect = icon.element.CurrentBoundingRectangle
                    cx = (rect.left + rect.right) // 2
                    cy = (rect.top + rect.bottom) // 2
                    import pyautogui
                    pyautogui.click(cx, cy)
                    return True

            logger.warning("Tray icon '%s' not found", name)
            return False
        except Exception as exc:
            logger.error("Failed to click tray icon '%s': %s", name, exc)
            return False

    # ================================================================
    # Taskbar state
    # ================================================================

    def get_taskbar_state(self) -> dict[str, Any]:
        """Get taskbar visibility and position state.

        Returns:
            Dict with keys: visible, position, auto_hide, bounds.
        """
        state: dict[str, Any] = {
            "visible": False,
            "position": "bottom",
            "auto_hide": False,
            "bounds": None,
        }
        try:
            import win32gui

            hwnd = win32gui.FindWindow(self._TASKBAR_CLASS, None)
            if hwnd:
                state["visible"] = bool(win32gui.IsWindowVisible(hwnd))

                # Get bounds
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                state["bounds"] = {
                    "left": left, "top": top,
                    "right": right, "bottom": bottom,
                    "width": right - left,
                    "height": bottom - top,
                }

                # Determine position from bounds
                try:
                    import win32api
                    screen_height = win32api.GetSystemMetrics(1)
                except ImportError:
                    screen_height = 1080
                if top == 0 and bottom < 100:
                    state["position"] = "top"
                elif bottom >= screen_height:
                    state["position"] = "bottom"

                # Check auto-hide
                try:
                    appbar_data = win32gui.SendMessage(
                        hwnd, 0x000004D4, 0, 0,  # ABM_GETSTATE
                    )
                    state["auto_hide"] = bool(appbar_data & 0x00000001)
                except Exception:
                    pass

        except Exception as exc:
            logger.debug("Failed to get taskbar state: %s", exc)
        return state

    # ================================================================
    # Internal helpers
    # ================================================================

    def _can_import_win32api(self) -> bool:
        """Check if win32api is available."""
        try:
            import win32api  # noqa: F401
            return True
        except ImportError:
            return False

    def _find_taskbar_element(self, root: Any) -> Any:
        """Find the taskbar (Shell_TrayWnd) element."""
        try:
            uia = self._get_uia()
            condition = uia.iuia.CreatePropertyCondition(
                uia._uia_dll.UIA_ClassNamePropertyId, self._TASKBAR_CLASS,
            )
            return root.FindFirst(uia.TREE_SCOPE_CHILDREN, condition)
        except Exception:
            return None

    def _find_child_by_class(self, parent: Any, class_name: str) -> Any:
        """Find a child element by class name."""
        try:
            uia = self._get_uia()
            condition = uia.iuia.CreatePropertyCondition(
                uia._uia_dll.UIA_ClassNamePropertyId, class_name,
            )
            return parent.FindFirst(uia.TREE_SCOPE_DESCENDANTS, condition)
        except Exception:
            return None

    def _find_overflow_tray(self, root: Any) -> Any:
        """Find the overflow tray window (hidden icons)."""
        try:
            uia = self._get_uia()
            condition = uia.iuia.CreatePropertyCondition(
                uia._uia_dll.UIA_ClassNamePropertyId, self._TRAY_OVERFLOW_CLASS,
            )
            overflow_window = root.FindFirst(uia.TREE_SCOPE_CHILDREN, condition)
            if overflow_window:
                return self._find_child_by_class(overflow_window, self._TRAY_CLASS)
        except Exception:
            pass
        return None

    def _walk_taskbar_buttons(self, tasklist: Any) -> list[TaskbarItem]:
        """Walk buttons in the task list element."""
        items: list[TaskbarItem] = []
        try:
            uia = self._get_uia()
            walker = uia.control_walker

            child = walker.GetFirstChildElement(tasklist)
            while child is not None:
                try:
                    name = child.CurrentName or ""
                    control_type = child.CurrentControlType

                    # Buttons (50000) and ListItems (50007) are taskbar buttons
                    if control_type in (50000, 50007):
                        tooltip = name  # Taskbar button names are tooltips
                        is_running = True  # In the task list = running

                        items.append(TaskbarItem(
                            name=name,
                            is_running=is_running,
                            tooltip=tooltip,
                            element=child,
                        ))
                except Exception:
                    pass

                try:
                    child = walker.GetNextSiblingElement(child)
                except Exception:
                    break
        except Exception as exc:
            logger.debug("Taskbar button walk failed: %s", exc)
        return items

    def _walk_tray_buttons(self, tray_element: Any) -> list[TaskbarItem]:
        """Walk tray icon buttons."""
        items: list[TaskbarItem] = []
        try:
            uia = self._get_uia()
            walker = uia.control_walker

            child = walker.GetFirstChildElement(tray_element)
            while child is not None:
                try:
                    name = child.CurrentName or ""
                    control_type = child.CurrentControlType

                    if control_type in (50000, 50007):  # Button or ListItem
                        items.append(TaskbarItem(
                            name=name,
                            is_running=True,
                            tooltip=name,
                            element=child,
                        ))
                except Exception:
                    pass

                try:
                    child = walker.GetNextSiblingElement(child)
                except Exception:
                    break
        except Exception as exc:
            logger.debug("Tray button walk failed: %s", exc)
        return items
