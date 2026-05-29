"""DialogService — System dialog driving via UIA + win32gui.

Windows equivalents of Peekaboo's macOS DialogService:
  - Open/Save dialogs (instead of NSOpenPanel/NSSavePanel)
  - MessageBox buttons (instead of NSAlert)
  - File picker interaction

Implementation:
  - System dialogs have class name #32770
  - Button IDs: IDOK=1, IDCANCEL=2, IDABORT=3, IDRETRY=4,
    IDIGNORE=5, IDYES=6, IDNO=7
  - Uses GetDlgItem to find controls

HB-01: Only reads/drives existing UI — no window creation.
HB-02: Must work without admin privileges.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# Standard dialog button IDs
IDOK = 1
IDCANCEL = 2
IDABORT = 3
IDRETRY = 4
IDIGNORE = 5
IDYES = 6
IDNO = 7

# Dialog class name
DIALOG_CLASS = "#32770"

# Button name to ID mapping
BUTTON_NAME_TO_ID: dict[str, int] = {
    "ok": IDOK,
    "cancel": IDCANCEL,
    "abort": IDABORT,
    "retry": IDRETRY,
    "ignore": IDIGNORE,
    "yes": IDYES,
    "no": IDNO,
    "&ok": IDOK,
    "&cancel": IDCANCEL,
    "&abort": IDABORT,
    "&retry": IDRETRY,
    "&ignore": IDIGNORE,
    "&yes": IDYES,
    "&no": IDNO,
}


@dataclass
class DialogButton:
    """A button in a system dialog."""

    name: str
    button_id: int  # Dialog button ID (IDOK=1, IDCANCEL=2, etc.)
    is_enabled: bool = True


class DialogService:
    """System dialog driving — Open/Save/MessageBox interaction.

    Usage::

        svc = DialogService()
        dialogs = svc.list_dialogs()
        buttons = svc.get_dialog_buttons(hwnd=12345)
        svc.click_dialog_button(hwnd=12345, button_id=IDOK)
        svc.set_dialog_text(hwnd=12345, text="Hello")
        svc.dismiss_dialog(hwnd=12345, action="ok")
        svc.wait_for_dialog(timeout=10.0)
    """

    def __init__(self, walker: Any = None) -> None:
        """Initialize DialogService.

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
    # Dialog enumeration
    # ================================================================

    def list_dialogs(self) -> list[dict[str, Any]]:
        """List open system dialogs.

        Enumerates top-level windows looking for the #32770
        dialog class name.

        Returns:
            List of dicts with keys: hwnd, title, class_name, visible.
        """
        dialogs: list[dict[str, Any]] = []
        try:
            import win32gui

            def _enum_cb(hwnd: int, _: Any) -> bool:
                try:
                    class_name = win32gui.GetClassName(hwnd)
                    if class_name == DIALOG_CLASS:
                        title = win32gui.GetWindowText(hwnd)
                        dialogs.append({
                            "hwnd": hwnd,
                            "title": title,
                            "class_name": class_name,
                            "visible": bool(win32gui.IsWindowVisible(hwnd)),
                        })
                except Exception:
                    pass
                return True

            win32gui.EnumWindows(_enum_cb, None)
        except ImportError:
            logger.debug("win32gui not available for dialog enumeration")
        except Exception as exc:
            logger.error("Failed to list dialogs: %s", exc)
        return dialogs

    def get_dialog_buttons(self, hwnd: int) -> list[DialogButton]:
        """Get buttons for a system dialog.

        Uses UIA to find all button elements within the dialog.

        Args:
            hwnd: Dialog window handle.

        Returns:
            List of DialogButton with name, ID, and enabled state.
        """
        buttons: list[DialogButton] = []
        try:
            uia = self._get_uia()
            root = uia.element_from_handle(hwnd)

            # Find all buttons (control type 50000)
            condition = uia.iuia.CreatePropertyCondition(
                uia._uia_dll.UIA_ControlTypePropertyId, 50000,
            )
            found_all = root.FindAll(uia.TREE_SCOPE_CHILDREN, condition)

            if found_all:
                for i in range(found_all.Length):
                    elem = found_all.GetElement(i)
                    try:
                        name = elem.CurrentName or ""
                        is_enabled = bool(elem.CurrentIsEnabled)

                        # Map name to button ID
                        button_id = BUTTON_NAME_TO_ID.get(
                            name.lower(), 0
                        )
                        if button_id == 0:
                            # Try to get the control ID via win32
                            button_id = self._get_control_id(elem)

                        buttons.append(DialogButton(
                            name=name,
                            button_id=button_id,
                            is_enabled=is_enabled,
                        ))
                    except Exception:
                        continue

        except Exception as exc:
            logger.error("Failed to get dialog buttons for HWND %s: %s", hwnd, exc)
        return buttons

    def click_dialog_button(self, hwnd: int, button_id: int) -> bool:
        """Click a dialog button by its ID.

        Uses BM_CLICK message or UIA InvokePattern to click the button.

        Args:
            hwnd: Dialog window handle.
            button_id: Button ID (IDOK=1, IDCANCEL=2, etc.).

        Returns:
            True if the button was found and clicked.
        """
        try:
            import win32gui

            # Find the button control by ID
            btn_hwnd = win32gui.GetDlgItem(hwnd, button_id)
            if btn_hwnd:
                # Send BM_CLICK
                win32gui.SendMessage(btn_hwnd, 0x00F5, 0, 0)  # BM_CLICK
                return True

            # Fallback: use UIA to find by name
            button_name = None
            for name, bid in BUTTON_NAME_TO_ID.items():
                if bid == button_id:
                    button_name = name.replace("&", "")
                    break

            if button_name:
                return self._click_uia_button(hwnd, button_name)

            logger.warning("Button ID %s not found in dialog %s", button_id, hwnd)
            return False
        except Exception as exc:
            logger.error(
                "Failed to click dialog button %s in HWND %s: %s",
                button_id, hwnd, exc,
            )
            return False

    def set_dialog_text(self, hwnd: int, text: str) -> bool:
        """Type text into the dialog's text field.

        Finds the first editable text field in the dialog and sets
        its value. Works for Open/Save dialogs' filename fields.

        Args:
            hwnd: Dialog window handle.
            text: Text to set.

        Returns:
            True if a text field was found and text was set.
        """
        try:
            uia = self._get_uia()
            root = uia.element_from_handle(hwnd)

            # Find edit control (control type 50004 = Edit)
            condition = uia.iuia.CreatePropertyCondition(
                uia._uia_dll.UIA_ControlTypePropertyId, 50004,
            )
            found = root.FindFirst(uia.TREE_SCOPE_DESCENDANTS, condition)

            if found:
                # Try ValuePattern first
                result = self._get_walker().try_set_value(found, text)
                if result and result.success:
                    return True

                # Fallback: click + type
                rect = found.CurrentBoundingRectangle
                cx = (rect.left + rect.right) // 2
                cy = (rect.top + rect.bottom) // 2
                import pyautogui
                pyautogui.click(cx, cy)
                time.sleep(0.1)
                pyautogui.hotkey("ctrl", "a")
                pyautogui.write(text, interval=0.02)
                return True

            logger.warning("No text field found in dialog %s", hwnd)
            return False
        except Exception as exc:
            logger.error("Failed to set dialog text: %s", exc)
            return False

    def dismiss_dialog(self, hwnd: int, action: str = "cancel") -> bool:
        """Dismiss a dialog by action (ok/cancel/close).

        Args:
            hwnd: Dialog window handle.
            action: "ok", "cancel", "close", "yes", "no", or a button ID string.

        Returns:
            True if the dialog was dismissed.
        """
        try:
            # Map action to button ID
            action_lower = action.lower()
            button_id = BUTTON_NAME_TO_ID.get(action_lower)

            if button_id is not None:
                return self.click_dialog_button(hwnd, button_id)

            if action_lower == "close":
                try:
                    import win32gui
                    win32gui.PostMessage(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                    return True
                except Exception:
                    pass

            logger.warning("Unknown dismiss action: %s", action)
            return False
        except Exception as exc:
            logger.error("Failed to dismiss dialog: %s", exc)
            return False

    def wait_for_dialog(
        self,
        timeout: float = 10.0,
        poll_interval: float = 0.5,
    ) -> int | None:
        """Wait for a system dialog to appear.

        Polls for the #32770 dialog class until timeout.

        Args:
            timeout: Maximum wait time in seconds.
            poll_interval: Polling interval in seconds.

        Returns:
            HWND of the found dialog, or None if timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            dialogs = self.list_dialogs()
            visible = [d for d in dialogs if d.get("visible")]
            if visible:
                return visible[0]["hwnd"]
            time.sleep(poll_interval)

        logger.debug("No dialog appeared within %.1fs", timeout)
        return None

    # ================================================================
    # Internal helpers
    # ================================================================

    def _click_uia_button(self, hwnd: int, button_name: str) -> bool:
        """Click a button in a dialog by name via UIA."""
        try:
            uia = self._get_uia()
            root = uia.element_from_handle(hwnd)

            condition = uia.iuia.CreatePropertyCondition(
                uia._uia_dll.UIA_NamePropertyId, button_name,
            )
            found = root.FindFirst(uia.TREE_SCOPE_DESCENDANTS, condition)
            if found:
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
        except Exception as exc:
            logger.debug("UIA button click failed: %s", exc)
        return False

    def _get_control_id(self, elem: Any) -> int:
        """Try to get the control ID from a UIA element."""
        try:
            # The AutomationId property sometimes contains the control ID
            auto_id = elem.CurrentAutomationId or ""
            if auto_id.isdigit():
                return int(auto_id)
        except Exception:
            pass
        return 0
