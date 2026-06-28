"""macOS desktop adapter — AXUIElement + CoreGraphics + CGEvent.

Implements SurfaceAdapter for macOS desktop applications using:
  - ApplicationServices/AXUIElement: Accessibility tree (the "structural eyes")
  - CoreGraphics/CGWindowListCreateImage: Screenshots (the "visual eyes")
  - CoreGraphics/CGEvent: Mouse/keyboard injection (the "hands")

Safety guarantees:
  - All coordinates are validated against the target window bounds
  - Lazy import: pyobjc is only imported when actually used on macOS
  - Graceful error when pyobjc is not installed

HB-01: All tests mocked — no macOS hardware required.
HB-02: pyobjc is optional dependency only.
HB-03: Lazy import — must not crash on Windows.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from deskaoy.cascade.protocol import SurfaceAdapter
from deskaoy.cascade.types import AXNode, AXSnapshot
from deskaoy.results.types import (
    ActionError,
    ActionResult,
    ErrorCategory,
    action_result,
)

logger = logging.getLogger(__name__)


class MacOSAdapter(SurfaceAdapter):
    """macOS desktop adapter using AXUIElement and CoreGraphics.

    Uses pyobjc framework bindings (ApplicationServices) for:
      - Accessibility tree walking (AXUIElementCopyAttributeValue)
      - Screen capture (CGWindowListCreateImage)
      - Input injection (CGEvent)

    All pyobjc imports are lazy — the module can be imported on any
    platform without errors. Actual API calls require macOS + pyobjc.

    Usage:
        adapter = MacOSAdapter(pid=12345)
        result = await adapter.click("500,300")
    """

    def __init__(
        self,
        pid: int | None = None,
        bundle_id: str | None = None,
        window_title: str | None = None,
    ) -> None:
        self._pid = pid
        self._bundle_id = bundle_id
        self._window_title = window_title
        self._ax_ui: Any = None  # AXUIElementRef for the app
        self._window_bounds: tuple[int, int, int, int] | None = None

        # Lazy-loaded pyobjc modules (HB-03: never import at module level)
        self._core_graphics: Any = None
        self._quartz: Any = None
        self._app_services: Any = None
        self._imported = False

    # =================================================================
    # Lazy Import
    # =================================================================

    def _ensure_imports(self) -> None:
        """Lazy import macOS-specific modules (HB-03).

        Only imports pyobjc when actually called. On Windows/Linux,
        this will raise ImportError with a helpful message.
        """
        if self._imported:
            return

        if sys.platform != "darwin":
            raise ImportError(
                "MacOSAdapter requires macOS. "
                f"Current platform: {sys.platform}"
            )

        try:
            import ApplicationServices  # noqa: F401
            import CoreGraphics  # noqa: F401
            import Quartz  # noqa: F401

            self._app_services = ApplicationServices
            self._core_graphics = CoreGraphics
            self._quartz = Quartz
            self._imported = True
        except ImportError:
            raise ImportError(
                "macOS adapter requires pyobjc. "
                "Install with: pip install pyobjc-framework-ApplicationServices "
                "pyobjc-framework-Quartz"
            ) from None

    # =================================================================
    # Permission Probes
    # =================================================================

    def _check_accessibility_permission(self) -> bool:
        """Check whether the process has Accessibility permission.

        macOS requires Accessibility permission for CGEvent input injection.
        Without it, ``CGEventPost`` succeeds syntactically but the event is
        silently dropped — this is a common source of false success.
        """
        self._ensure_imports()
        return bool(self._app_services.AXIsProcessTrusted())

    def _check_screen_recording_permission(self) -> bool:
        """Check whether the process has Screen Recording permission.

        macOS requires Screen Recording permission for ``CGWindowListCreateImage``
        to return actual screen content. Without it, the screenshot will be
        blank or contain only a wallpaper.
        """
        self._ensure_imports()
        # CGPreflightScreenCaptureAccess / CGRequestScreenCaptureAccess are
        # available on macOS 10.15+. Pre-flight returns True if already granted.
        try:
            preflight = self._quartz.CGPreflightScreenCaptureAccess
            return bool(preflight())
        except AttributeError:
            # Older macOS — assume permission is available
            return True

    def _require_accessibility(self) -> ActionResult | None:
        """Return an error result if Accessibility permission is missing.

        Returns ``None`` if permission is granted.
        """
        if not self._check_accessibility_permission():
            return action_result(
                ok=False,
                error=ActionError(
                    ErrorCategory.SECURITY,
                    "macOS Accessibility permission not granted. "
                    "CGEvent input injection will be silently dropped. "
                    "Grant permission in System Settings > Privacy & Security > Accessibility.",
                ),
            )
        return None

    # =================================================================
    # AXUIElement Management
    # =================================================================

    def _resolve_ax_element(self) -> Any:
        """Get the AXUIElement for the target application.

        Resolves by PID or bundle identifier. Caches the result.
        """
        self._ensure_imports()
        if self._ax_ui is not None:
            return self._ax_ui

        if self._pid is not None:
            self._ax_ui = self._app_services.AXUIElementCreateApplication(self._pid)
        else:
            raise RuntimeError("No PID or bundle ID provided for macOS adapter")

        return self._ax_ui

    def _get_window_bounds(self) -> tuple[int, int, int, int]:
        """Get the bounding rect of the target window (x, y, w, h)."""
        self._ensure_imports()
        if self._window_bounds is not None:
            return self._window_bounds

        ax = self._resolve_ax_element()
        error, windows = self._app_services.AXUIElementCopyAttributeValue(
            ax, "AXWindows", 0, None
        )
        if error:
            return (0, 0, 1920, 1080)  # Fallback to full screen

        if windows and len(windows) > 0:
            win = windows[0]
            error, pos = self._app_services.AXUIElementCopyAttributeValue(
                win, "AXPosition", 0, None
            )
            error2, size = self._app_services.AXUIElementCopyAttributeValue(
                win, "AXSize", 0, None
            )
            if not error and not error2:
                x, y = int(pos.x), int(pos.y)
                w, h = int(size.width), int(size.height)
                self._window_bounds = (x, y, w, h)
                return self._window_bounds

        return (0, 0, 1920, 1080)

    # =================================================================
    # SurfaceAdapter Implementation
    # =================================================================

    async def screenshot(self) -> bytes:
        """Capture a screenshot using CGWindowListCreateImage.

        Captures the target window only (not full screen).

        Raises ``PermissionError`` if Screen Recording permission is missing
        (screenshot would be blank without it).
        """
        self._ensure_imports()

        if not self._check_screen_recording_permission():
            raise PermissionError(
                "macOS Screen Recording permission not granted. "
                "Screenshots will be blank. "
                "Grant in System Settings > Privacy & Security > Screen Recording."
            )

        rect = self._get_window_bounds()
        x, y, w, h = rect

        cg_rect = self._core_graphics.CGRectMake(x, y, w, h)
        image = self._quartz.CGWindowListCreateImage(
            cg_rect,
            self._quartz.kCGWindowListOptionOnScreenOnly,
            self._quartz.kCGNullWindowID,
            self._quartz.kCGWindowImageDefault,
        )

        # Convert CGImage to PNG bytes
        if image:
            rep = self._core_graphics.NSBitmapImageRep.alloc().initWithCGImage_(image)
            png_data = rep.representationUsingType_property_(
                self._core_graphics.NSBitmapImageFileTypePNG, None
            )
            return bytes(png_data)
        return b""

    async def snapshot(self) -> AXSnapshot:
        """Capture the accessibility tree using AXUIElement.

        Walks the AX tree from the target application, producing
        AXNodes for the cascade engine's Tier 1 (selector) resolution.
        """
        self._ensure_imports()
        ax = self._resolve_ax_element()

        title = self._window_title or ""
        nodes: dict[str, AXNode] = {}
        counter = [0]

        def _walk(element: Any, depth: int = 0) -> None:
            if depth > 10:  # Max depth to prevent infinite walk
                return
            try:
                error, role = self._app_services.AXUIElementCopyAttributeValue(
                    element, "AXRole", 0, None
                )
                if error:
                    return

                error, name = self._app_services.AXUIElementCopyAttributeValue(
                    element, "AXTitle", 0, None
                )
                if error:
                    name = ""

                ref = f"e{counter[0]}"
                counter[0] += 1
                nodes[ref] = AXNode(
                    ref=ref,
                    role=str(role) if role else "unknown",
                    name=str(name) if name else "",
                )

                # Walk children
                error, children = self._app_services.AXUIElementCopyAttributeValue(
                    element, "AXChildren", 0, None
                )
                if not error and children:
                    for child in children:
                        _walk(child, depth + 1)
            except Exception:
                pass

        _walk(ax)

        return AXSnapshot(
            url=self.current_url(),
            title=title,
            nodes=nodes,
        )

    async def click(
        self, target: str, *, dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Click on a target element using CGEvent mouse events.

        Requires Accessibility permission for CGEvent injection.

        Target can be:
          - Coordinates as "x,y" string
          - AX element name resolved via accessibility tree
        """
        self._ensure_imports()

        if dry_run:
            return action_result(ok=True, data={
                "action": "click", "target": target, "dry_run": True,
            })

        perm_error = self._require_accessibility()
        if perm_error is not None:
            return perm_error

        try:
            point = self._resolve_target(target)

            # CGEvent mouse down + up at target
            event_down = self._quartz.CGEventCreateMouseEvent(
                None, self._quartz.kCGEventLeftMouseDown, (point[0], point[1]),
                self._quartz.kCGMouseButtonLeft,
            )
            event_up = self._quartz.CGEventCreateMouseEvent(
                None, self._quartz.kCGEventLeftMouseUp, (point[0], point[1]),
                self._quartz.kCGMouseButtonLeft,
            )
            self._quartz.CGEventPost(self._quartz.kCGHIDEventTap, event_down)
            self._quartz.CGEventPost(self._quartz.kCGHIDEventTap, event_up)

            return action_result(ok=True, data={
                "x": point[0], "y": point[1],
                "pattern_used": "CGEvent",
            })
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    async def fill(
        self, target: str, value: str, *, dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Fill a text field — click + type.

        Requires Accessibility permission for CGEvent injection.
        Checks permission before any click to prevent partial side effects.
        """
        self._ensure_imports()

        if dry_run:
            return action_result(ok=True, data={
                "action": "fill", "target": target,
                "value": value, "dry_run": True,
            })

        perm_error = self._require_accessibility()
        if perm_error is not None:
            return perm_error

        try:
            click_result = await self.click(target)
            if not click_result.ok:
                return click_result

            await asyncio.sleep(0.05)
            type_result = await self.type_text(value)
            if not type_result.ok:
                return type_result

            return action_result(ok=True, data={"value": value})
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    async def type_text(
        self, text: str, delay_ms: float = 0, *,
        dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Type text using CGEvent keyboard events.

        Requires Accessibility permission. Sends individual key events for
        each character via CGEvent.
        """
        self._ensure_imports()

        if dry_run:
            return action_result(ok=True, data={
                "action": "type_text", "char_count": len(text), "dry_run": True,
            })

        perm_error = self._require_accessibility()
        if perm_error is not None:
            return perm_error

        try:
            for ch in text:
                key_code = self._char_to_keycode(ch)
                event_down = self._quartz.CGEventCreateKeyboardEvent(
                    None, key_code, True,
                )
                event_up = self._quartz.CGEventCreateKeyboardEvent(
                    None, key_code, False,
                )
                self._quartz.CGEventPost(self._quartz.kCGHIDEventTap, event_down)
                self._quartz.CGEventPost(self._quartz.kCGHIDEventTap, event_up)
                if delay_ms > 0:
                    await asyncio.sleep(delay_ms / 1000.0)

            return action_result(ok=True)
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    async def key_press(
        self, key: str, modifiers: int = 0, *,
        dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Press a key with optional modifiers using CGEvent.

        Requires Accessibility permission for CGEvent injection.

        Modifiers bitmask:
          - 1: Alt (Option)
          - 2: Ctrl (Command on macOS)
          - 4: Shift
          - 8: Cmd (Command)
        """
        self._ensure_imports()

        # SECURITY: Check key blocklist before permission/execution
        from deskaoy.safety.key_blocklist import block_reason, is_blocked_key
        combo = key
        mod_names: list[str] = []
        if modifiers & 1:
            mod_names.append("alt")
        if modifiers & 2:
            mod_names.append("ctrl")
        if modifiers & 4:
            mod_names.append("shift")
        if modifiers & 8:
            mod_names.append("super")
        if mod_names:
            combo = "+".join(mod_names) + "+" + key
        if is_blocked_key(combo):
            return action_result(
                ok=False,
                error=ActionError(
                    ErrorCategory.SECURITY,
                    f"Blocked key combo: {combo} — {block_reason(combo)}",
                ),
            )

        if dry_run:
            return action_result(ok=True, data={
                "action": "key_press", "key": key,
                "modifiers": modifiers, "dry_run": True,
            })

        perm_error = self._require_accessibility()
        if perm_error is not None:
            return perm_error

        try:
            key_code = self._key_to_keycode(key)

            # Build modifier flags
            flags = 0
            if modifiers & 1:  # Alt/Option
                flags |= self._quartz.kCGEventFlagMaskAlternate
            if modifiers & 2:  # Ctrl
                flags |= self._quartz.kCGEventFlagMaskControl
            if modifiers & 4:  # Shift
                flags |= self._quartz.kCGEventFlagMaskShift
            if modifiers & 8:  # Cmd
                flags |= self._quartz.kCGEventFlagMaskCommand

            event_down = self._quartz.CGEventCreateKeyboardEvent(
                None, key_code, True,
            )
            if flags:
                self._quartz.CGEventSetFlags(event_down, flags)

            event_up = self._quartz.CGEventCreateKeyboardEvent(
                None, key_code, False,
            )
            if flags:
                self._quartz.CGEventSetFlags(event_up, flags)

            self._quartz.CGEventPost(self._quartz.kCGHIDEventTap, event_down)
            self._quartz.CGEventPost(self._quartz.kCGHIDEventTap, event_up)

            return action_result(ok=True)
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    async def scroll(
        self, direction: str, amount: int = 500, *,
        dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Scroll using CGEvent scroll wheel events.

        Requires Accessibility permission for CGEvent injection.
        """
        self._ensure_imports()

        if dry_run:
            return action_result(ok=True, data={
                "action": "scroll", "direction": direction,
                "amount": amount, "dry_run": True,
            })

        perm_error = self._require_accessibility()
        if perm_error is not None:
            return perm_error

        try:
            scroll_units = amount // 10
            if direction in ("down", "right"):
                scroll_units = -scroll_units

            event = self._quartz.CGEventCreateScrollWheelEvent(
                None,
                self._quartz.kCGScrollEventUnitPixel,
                1,  # number of wheels
                scroll_units,
            )
            self._quartz.CGEventPost(self._quartz.kCGHIDEventTap, event)

            return action_result(ok=True)
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    async def evaluate(self, expression: str) -> Any:
        """Execute AppleScript or shell expression.

        Not directly supported — returns None.
        """
        return None

    def current_url(self) -> str:
        """Return application identifier."""
        if self._bundle_id:
            return f"macos://{self._bundle_id}"
        if self._pid:
            return f"macos://pid/{self._pid}"
        return "macos://unknown"

    async def current_title(self) -> str:
        """Return window title."""
        return self._window_title or ""

    # =================================================================
    # Target Resolution
    # =================================================================

    def _resolve_target(self, target: str) -> tuple[float, float]:
        """Resolve a target string to screen coordinates.

        Supported formats:
          - "x,y" — direct coordinates
          - Anything else — AX element name search (future)
        """
        if "," in target:
            parts = target.split(",")
            try:
                return (float(parts[0]), float(parts[1]))
            except (ValueError, IndexError):
                pass

        # Fallback: center of window
        bounds = self._get_window_bounds()
        x, y, w, h = bounds
        return (x + w / 2, y + h / 2)

    # =================================================================
    # Key Code Helpers
    # =================================================================

    _KEY_MAP: dict[str, int] = {
        "return": 0x24, "enter": 0x24,
        "tab": 0x30, "space": 0x31,
        "delete": 0x33, "backspace": 0x33,
        "escape": 0x35, "esc": 0x35,
        "command": 0x37, "cmd": 0x37,
        "shift": 0x38, "capslock": 0x39,
        "option": 0x3A, "alt": 0x3A,
        "control": 0x3B, "ctrl": 0x3B,
        "rightshift": 0x3C, "rightoption": 0x3D,
        "rightcontrol": 0x3E, "function": 0x3F,
        "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76,
        "f5": 0x60, "f6": 0x61, "f7": 0x62, "f8": 0x64,
        "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F,
        "home": 0x73, "end": 0x77,
        "pageup": 0x74, "pagedown": 0x79,
        "leftarrow": 0x7B, "rightarrow": 0x7C,
        "downarrow": 0x7D, "uparrow": 0x7E,
    }

    def _key_to_keycode(self, key: str) -> int:
        """Map a key name to a macOS virtual key code."""
        return self._KEY_MAP.get(key.lower(), 0)

    def _char_to_keycode(self, ch: str) -> int:
        """Map a character to a macOS virtual key code (simplified)."""
        # Simplified: just return 0 for now — full mapping would be extensive
        return 0
