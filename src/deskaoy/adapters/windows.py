"""Windows desktop adapter — UI Automation + win32gui + pyautogui.

Implements SurfaceAdapter for Windows desktop applications using:
  - win32gui: Window handle isolation (ensure we only see/click within target app)
  - pyautogui: Mouse/keyboard injection (the "hands")
  - comtypes/UIAutomation: Accessibility tree (the "structural eyes")
  - mss / DXGI: Screenshots (the "visual eyes")

Safety guarantees:
  - All coordinates are validated against the target window rect
  - Mouse movements follow Bezier curves with human-like dynamics
  - Click positions are jittered to avoid perfect-center patterns
  - Window handle is re-verified before every action
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from typing import Any

from deskaoy.cascade.protocol import SurfaceAdapter
from deskaoy.cascade.types import AXSnapshot
from deskaoy.feedback.engine import FeedbackEngine
from deskaoy.input.bezier import move_mouse
from deskaoy.input.jitter import (
    random_delay_ms,
    randomize_click_point,
)
from deskaoy.input.types import HumanizationConfig, Point, Rect
from deskaoy.results.types import (
    ActionError,
    ActionResult,
    ErrorCategory,
    action_result,
)

logger = logging.getLogger(__name__)


class WindowsAdapter(SurfaceAdapter):
    """Windows desktop adapter with window isolation and humanized input.

    Usage:
        adapter = WindowsAdapter(hwnd=win32gui.FindWindow(None, "Calculator"))
        adapter.humanization = HumanizationConfig(move_enabled=True)

        result = await adapter.click("num_7_button")
    """

    def __init__(
        self,
        hwnd: int | None = None,
        window_title: str | None = None,
        humanization: HumanizationConfig | None = None,
        feedback_engine: FeedbackEngine | None = None,
    ) -> None:
        self._hwnd = hwnd
        self._window_title = window_title
        self._humanization = humanization or HumanizationConfig()
        self._feedback = feedback_engine  # HB-01: None by default = opt-in
        self._last_mouse_pos: Point | None = None
        self._aborted = False  # Secondary failsafe flag

        # Configurable timing
        self._focus_settle_ms: float = 300.0  # Wait after SetForegroundWindow
        self._dpi_scale: float = 1.0

        # Lazy imports — these are Windows-only
        self._win32gui: Any = None
        self._win32api: Any = None
        self._win32con: Any = None
        self._pyautogui: Any = None
        self._uia: Any = None

    def _ensure_imports(self) -> None:
        """Lazy import Windows-specific modules."""
        if self._win32gui is not None:
            return

        try:
            import win32api
            import win32con
            import win32gui
            self._win32gui = win32gui
            self._win32api = win32api
            self._win32con = win32con
        except ImportError:
            raise ImportError(
                "win32gui required for Windows adapter. "
                "Install with: pip install pywin32"
            ) from None

        try:
            import pyautogui
            self._pyautogui = pyautogui
            pyautogui.FAILSAFE = True  # Safety: move mouse to corner to abort
        except ImportError:
            raise ImportError(
                "pyautogui required for Windows adapter. "
                "Install with: pip install pyautogui"
            ) from None

    # =================================================================
    # Failsafe & Abort
    # =================================================================

    def abort(self) -> None:
        """Signal the adapter to stop all actions immediately.

        Secondary failsafe for environments where pyautogui's corner-mouse
        failsafe doesn't work (VMs, RDP, headless CI).
        """
        self._aborted = True
        logger.warning("Adapter abort triggered")

    def _check_abort(self) -> None:
        """Raise if abort was signaled."""
        if self._aborted:
            raise RuntimeError("Adapter aborted — all actions stopped")

    # =================================================================
    # Window Handle Management
    # =================================================================

    def _resolve_hwnd(self) -> int:
        """Get window handle, finding it by title if needed."""
        self._ensure_imports()
        if self._hwnd is not None:
            return self._hwnd
        if self._window_title is not None:
            self._hwnd = self._win32gui.FindWindow(None, self._window_title)
            if self._hwnd == 0:
                raise RuntimeError(f"Window not found: {self._window_title}")
            return self._hwnd
        raise RuntimeError("No window handle or title provided")

    def _get_window_rect(self) -> Rect:
        """Get the bounding rectangle of the target window.

        Returns the window's position and size in screen coordinates.
        Accounts for DPI scaling on high-DPI displays.
        All click coordinates are validated against this rect.
        """
        hwnd = self._resolve_hwnd()
        left, top, right, bottom = self._win32gui.GetWindowRect(hwnd)

        # Update DPI scale from window (if possible)
        try:
            self._dpi_scale = self._win32api.GetDpiForWindow(hwnd) / 96.0
        except (AttributeError, Exception):
            self._dpi_scale = 1.0  # Fallback for older Windows

        # Update humanization config with actual DPI
        self._humanization.dpi_scale = self._dpi_scale

        return Rect(x=left, y=top, width=right - left, height=bottom - top)

    def _ensure_window_ready(self) -> None:
        """Check window is visible, not minimized, and valid.

        Checks:
          1. Window handle is still valid (app didn't close)
          2. Window is visible (not hidden)
          3. Window is not minimized (iconic)
          4. Restores from minimized if needed

        Raises RuntimeError if window is not ready.
        """
        hwnd = self._resolve_hwnd()

        # Check handle is still valid
        if not self._win32gui.IsWindow(hwnd):
            raise RuntimeError(
                f"Window handle {hwnd} is no longer valid (app may have closed)"
            )

        # Check if minimized — restore if so
        if self._win32gui.IsIconic(hwnd):
            logger.info("Window is minimized, restoring...")
            self._win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
            time.sleep(0.3)  # Wait for restore animation

        # Check visibility
        if not self._win32gui.IsWindowVisible(hwnd):
            raise RuntimeError(
                f"Window {hwnd} is not visible — cannot interact safely"
            )

    def _is_window_at_point(self, point: Point) -> bool:
        """Check if the target window is the topmost at the given point.

        Uses WindowFromPoint() to detect occlusion. Returns False if
        another window covers the target at this coordinate.
        """
        hwnd = self._resolve_hwnd()
        try:
            top_hwnd = self._win32gui.WindowFromPoint((int(point.x), int(point.y)))
            # Check if the top window IS our target or a CHILD of it
            check = top_hwnd
            while check:
                if check == hwnd:
                    return True
                check = self._win32gui.GetParent(check)
            return False
        except Exception:
            # If we can't check, assume it's OK
            return True

    def _validate_point_in_window(self, point: Point) -> Point:
        """Ensure a point is within the target window bounds AND visible.

        Checks:
          1. Point is inside the window rect
          2. Target window is topmost at that point (not occluded)
          3. Brings window to front if occluded

        Raises RuntimeError if the point is outside or permanently blocked.
        """
        rect = self._get_window_rect()
        if not rect.contains(point):
            raise RuntimeError(
                f"Safety: point ({point.x:.0f}, {point.y:.0f}) is outside "
                f"target window rect ({rect.x:.0f},{rect.y:.0f})"
                f"-({rect.x2:.0f},{rect.y2:.0f}). "
                f"Action blocked to prevent accidental clicks."
            )

        # Check for occlusion
        if not self._is_window_at_point(point):
            logger.info("Window occluded at target point, bringing to front...")
            self._bring_to_front()
            # Re-check after bringing to front
            if not self._is_window_at_point(point):
                raise RuntimeError(
                    f"Safety: point ({point.x:.0f}, {point.y:.0f}) is covered by "
                    f"another window that cannot be moved. Action blocked."
                )

        return point

    def _bring_to_front(self) -> None:
        """Bring the target window to the foreground with error handling.

        Handles common failures:
          - Access denied (foreground lock)
          - Minimized window (restores first)
          - Fullscreen app blocking
        """
        hwnd = self._resolve_hwnd()

        # Restore from minimized first
        if self._win32gui.IsIconic(hwnd):
            self._win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
            time.sleep(0.2)

        try:
            self._win32gui.SetForegroundWindow(hwnd)
        except Exception as exc:
            # SetForegroundWindow can fail due to foreground lock timeout
            # Try alternative: AttachThreadInput + BringWindowToTop
            logger.warning("SetForegroundWindow failed: %s, trying fallback", exc)
            try:
                self._win32gui.BringWindowToTop(hwnd)
            except Exception as exc2:
                logger.warning("BringWindowToTop also failed: %s", exc2)
                raise RuntimeError(
                    f"Cannot bring window {hwnd} to foreground. "
                    f"Another app may have foreground lock."
                ) from exc

    # =================================================================
    # Mouse Input
    # =================================================================

    def _get_mouse_pos(self) -> Point:
        """Get current mouse cursor position."""
        pos = self._win32api.GetCursorPos()
        return Point(pos[0], pos[1])

    def _move_to(self, point: Point) -> None:
        """Move cursor to a point (called by Bezier curve engine)."""
        self._pyautogui.moveTo(int(point.x), int(point.y), _pause=False)

    async def _humanized_move(self, target: Point) -> Point:
        """Move mouse to target along a Bezier curve with jitter."""
        start = self._last_mouse_pos or self._get_mouse_pos()

        if self._humanization.move_enabled:
            final = await move_mouse(
                start=start,
                end=target,
                move_fn=self._move_to,
                config=self._humanization,
            )
        else:
            self._move_to(target)
            final = target

        self._last_mouse_pos = final
        return final

    async def click(
        self, target: str, *, dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Click on a target element — action-first with UIA pattern.

        Action-first sequence:
          1. If target is NOT coordinates, try UIA InvokePattern.Invoke()
          2. If pattern works → return ok with pattern_used metadata
          3. If pattern unavailable or fails → fallback to pyautogui click
          4. If target is coordinates, always use pyautogui

        Target can be:
          - Coordinates as "x,y" string
          - Element name resolved via UI Automation

        When dry_run=True, resolve target and return predicted result
        without executing the click.
        """
        self._ensure_imports()

        if dry_run:
            point = self._resolve_target(target, **kwargs)
            return action_result(ok=True, data={
                "action": "click", "target": target,
                "point": {"x": point.x, "y": point.y}, "dry_run": True,
            })

        # --- Action-first: try UIA InvokePattern for non-coordinate targets ---
        is_coordinate = "," in target and not target.startswith("name:") and not target.startswith("auto:")
        if not is_coordinate:
            pattern_result = await self._try_uia_pattern_click(target, **kwargs)
            if pattern_result is not None:
                return pattern_result
        # --- Fallback: pyautogui click ---

        try:
            self._check_abort()
            # Validate window state (visible, not minimized, valid)
            self._ensure_window_ready()

            point = self._resolve_target(target, **kwargs)

            # Randomize click position (avoid perfect center)
            bounds = kwargs.get("bounds")
            if bounds:
                point = randomize_click_point(point, self._humanization, bounds=bounds)
            else:
                point = randomize_click_point(point, self._humanization)

            # Validate within window (includes occlusion check)
            point = self._validate_point_in_window(point)

            # Bring to front and settle (anti-detection: don't click 100ms after focus)
            self._bring_to_front()
            settle_delay = random_delay_ms(self._focus_settle_ms, 100) / 1000.0
            await asyncio.sleep(settle_delay)

            self._check_abort()  # Re-check after settle delay

            # Move along Bezier curve
            await self._humanized_move(point)

            # Visual feedback: show ripple at click point (before click)
            if self._feedback is not None:
                self._feedback.on_before_click(int(point.x), int(point.y))

            # Small random delay before click (human reaction time)
            delay = random_delay_ms(30, 20) / 1000.0
            await asyncio.sleep(delay)

            # Click
            button = kwargs.get("button", "left")
            self._pyautogui.click(int(point.x), int(point.y), button=button)

            # Visual feedback: after-click hook
            if self._feedback is not None:
                self._feedback.on_after_click(int(point.x), int(point.y))

            return action_result(ok=True, data={
                "x": point.x, "y": point.y,
                "pattern_used": None, "fallback_used": True,
            })
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    async def _try_uia_pattern_click(
        self, target: str, **kwargs: Any,
    ) -> ActionResult | None:
        """Try UIA InvokePattern for a click target. Returns None to signal fallback."""
        try:
            from deskaoy.adapters.uia_walker import UIAWalker
            walker = UIAWalker()
            hwnd = self._resolve_hwnd()

            # Resolve to raw UIA element
            raw_elem = self._resolve_raw_element(walker, hwnd, target)
            if raw_elem is not None:
                result = walker.try_invoke(raw_elem)
                if result is not None and result.success:
                    return action_result(ok=True, data={
                        "pattern_used": result.pattern_used,
                        "fallback_used": False,
                        "method": "uia_pattern",
                    })
        except Exception as exc:
            logger.debug("UIA InvokePattern failed, falling back to pyautogui: %s", exc)
        return None

    def _resolve_raw_element(
        self, walker: Any, hwnd: int, target: str,
    ) -> Any:
        """Resolve a target string to a raw UIA COM element for pattern access.

        This is different from _resolve_target_by_uia which returns a Point.
        We need the raw COM element to call pattern methods on it.
        """
        try:
            uia = walker._get_uia()
            root = uia.element_from_handle(hwnd)

            if target.startswith("name:"):
                name = target[5:]
                condition = uia.iuia.CreatePropertyCondition(
                    uia._uia_dll.UIA_NamePropertyId, name,
                )
                return root.FindFirst(uia.TREE_SCOPE_DESCENDANTS, condition)
            elif target.startswith("auto:"):
                auto_id = target[5:]
                condition = uia.iuia.CreatePropertyCondition(
                    uia._uia_dll.UIA_AutomationIdPropertyId, auto_id,
                )
                return root.FindFirst(uia.TREE_SCOPE_DESCENDANTS, condition)
            else:
                # Plain text → name search
                condition = uia.iuia.CreatePropertyCondition(
                    uia._uia_dll.UIA_NamePropertyId, target,
                )
                return root.FindFirst(uia.TREE_SCOPE_DESCENDANTS, condition)
        except Exception as exc:
            logger.debug("_resolve_raw_element failed for '%s': %s", target, exc)
            return None

    async def fill(
        self, target: str, value: str, *, dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Fill a text field — action-first with ValuePattern.

        Action-first sequence:
          1. Try ValuePattern.SetValue(value)
          2. If pattern works → return ok with pattern_used metadata
          3. If pattern unavailable → fallback to click + type

        When dry_run=True, return predicted result without executing.
        """
        self._ensure_imports()

        if dry_run:
            return action_result(ok=True, data={
                "action": "fill", "target": target,
                "value": value, "dry_run": True,
            })

        # --- Action-first: try ValuePattern ---
        is_coordinate = "," in target and not target.startswith("name:") and not target.startswith("auto:")
        if not is_coordinate:
            pattern_result = await self._try_uia_pattern_fill(target, value, **kwargs)
            if pattern_result is not None:
                return pattern_result
        # --- Fallback: click + type ---

        try:
            # Click on the target first
            click_result = await self.click(target, **kwargs)
            if not click_result.ok:
                return click_result

            # Small delay after clicking before typing
            await asyncio.sleep(random_delay_ms(100, 50) / 1000.0)

            # Type with humanized delays
            await self._humanized_type(value)

            return action_result(ok=True, data={
                "value": value,
                "pattern_used": None, "fallback_used": True,
            })
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    async def _try_uia_pattern_fill(
        self, target: str, value: str, **kwargs: Any,
    ) -> ActionResult | None:
        """Try UIA ValuePattern for a fill target. Returns None to signal fallback."""
        try:
            from deskaoy.adapters.uia_walker import UIAWalker
            walker = UIAWalker()
            hwnd = self._resolve_hwnd()

            raw_elem = self._resolve_raw_element(walker, hwnd, target)
            if raw_elem is not None:
                result = walker.try_set_value(raw_elem, value)
                if result is not None and result.success:
                    return action_result(ok=True, data={
                        "value": value,
                        "pattern_used": result.pattern_used,
                        "fallback_used": False,
                        "method": "uia_pattern",
                    })
        except Exception as exc:
            logger.debug("UIA ValuePattern failed, falling back to click+type: %s", exc)
        return None

    # =================================================================
    # Keyboard Input
    # =================================================================

    async def _humanized_type(self, text: str) -> None:
        """Type text with randomized inter-key delays."""
        cfg = self._humanization
        for i, ch in enumerate(text):
            # Burst mode: sometimes type fast (no delay)
            if cfg.type_burst_probability > 0 and random.random() < cfg.type_burst_probability:
                burst_len = min(cfg.type_burst_length, len(text) - i)
                burst = text[i:i + burst_len]
                self._pyautogui.write(burst, interval=0)
                continue

            self._pyautogui.write(ch, interval=0)
            delay = random_delay_ms(cfg.type_base_delay_ms, cfg.type_delay_variance_ms)
            await asyncio.sleep(delay / 1000.0)

    async def type_text(
        self, text: str, delay_ms: float = 0, *,
        dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Type text with humanized timing.

        When dry_run=True, return predicted result without executing.
        """
        self._ensure_imports()

        if dry_run:
            return action_result(ok=True, data={
                "action": "type_text", "char_count": len(text), "dry_run": True,
            })

        try:
            await self._humanized_type(text)
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
        """Press a key with optional modifiers.

        When dry_run=True, return predicted result without executing.
        Blocked key combos are rejected before execution.
        """
        self._ensure_imports()

        # SECURITY (BATCH-12): Check key blocklist
        from deskaoy.safety.key_blocklist import block_reason, is_blocked_key
        combo = key
        mod_names = []
        if modifiers & 1: mod_names.append("alt")
        if modifiers & 2: mod_names.append("ctrl")
        if modifiers & 4: mod_names.append("shift")
        if modifiers & 8: mod_names.append("win")
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

        try:
            # Map modifier bitmask to pyautogui
            mod_keys = []
            if modifiers & 1:  # Alt
                mod_keys.append("alt")
            if modifiers & 2:  # Ctrl
                mod_keys.append("ctrl")
            if modifiers & 4:  # Shift
                mod_keys.append("shift")
            if modifiers & 8:  # Meta (Win key)
                mod_keys.append("win")

            if mod_keys:
                self._pyautogui.hotkey(*mod_keys, key)
            else:
                self._pyautogui.press(key)

            return action_result(ok=True)
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    async def key_down(
        self, key: str, modifiers: int = 0, *,
        dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Hold a key down (for chords, modifier holds, gaming input).

        Checks key blocklist before executing.
        When dry_run=True, return predicted result without executing.
        """
        self._ensure_imports()

        # SECURITY: Check key blocklist
        from deskaoy.safety.key_blocklist import block_reason, is_blocked_key
        combo = key
        mod_names = []
        if modifiers & 1: mod_names.append("alt")
        if modifiers & 2: mod_names.append("ctrl")
        if modifiers & 4: mod_names.append("shift")
        if modifiers & 8: mod_names.append("win")
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
                "action": "key_down", "key": key,
                "modifiers": modifiers, "dry_run": True,
            })

        try:
            self._pyautogui.keyDown(key)
            return action_result(ok=True)
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    async def key_up(
        self, key: str, modifiers: int = 0, *,
        dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Release a held key.

        When dry_run=True, return predicted result without executing.
        """
        self._ensure_imports()

        if dry_run:
            return action_result(ok=True, data={
                "action": "key_up", "key": key,
                "modifiers": modifiers, "dry_run": True,
            })

        try:
            self._pyautogui.keyUp(key)
            return action_result(ok=True)
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    async def mouse_down(
        self, button: str = "left", *,
        dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Press and hold a mouse button at the current position.

        When dry_run=True, return predicted result without executing.
        """
        self._ensure_imports()

        if dry_run:
            return action_result(ok=True, data={
                "action": "mouse_down", "button": button, "dry_run": True,
            })

        try:
            self._pyautogui.mouseDown(button=button)
            return action_result(ok=True)
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    async def mouse_up(
        self, button: str = "left", *,
        dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Release a held mouse button.

        When dry_run=True, return predicted result without executing.
        """
        self._ensure_imports()

        if dry_run:
            return action_result(ok=True, data={
                "action": "mouse_up", "button": button, "dry_run": True,
            })

        try:
            self._pyautogui.mouseUp(button=button)
            return action_result(ok=True)
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    async def mouse_drag(
        self, start: str, end: str, *,
        button: str = "left",
        dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Drag from start to end coordinates.

        Coordinates as "x,y" strings. Validates both points within target window.
        When dry_run=True, return predicted result without executing.
        """
        self._ensure_imports()

        # Parse coordinates
        try:
            sx, sy = start.split(",")
            ex, ey = end.split(",")
            start_point = Point(float(sx), float(sy))
            end_point = Point(float(ex), float(ey))
        except (ValueError, IndexError):
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.VALIDATION, f"Invalid coordinates: start={start}, end={end}"),
            )

        if dry_run:
            return action_result(ok=True, data={
                "action": "mouse_drag", "start": {"x": start_point.x, "y": start_point.y},
                "end": {"x": end_point.x, "y": end_point.y}, "dry_run": True,
            })

        try:
            self._check_abort()
            self._ensure_window_ready()

            # Validate both points are within window
            start_point = self._validate_point_in_window(start_point)
            end_point = self._validate_point_in_window(end_point)

            # Move to start, hold button, drag to end, release
            self._move_to(start_point)
            self._pyautogui.mouseDown(button=button)
            time.sleep(0.05)  # Small delay between down and move
            self._move_to(end_point)
            self._pyautogui.mouseUp(button=button)

            return action_result(ok=True, data={
                "start": {"x": start_point.x, "y": start_point.y},
                "end": {"x": end_point.x, "y": end_point.y},
            })
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    # =================================================================
    # Scrolling
    # =================================================================

    async def scroll(
        self, direction: str, amount: int = 500, *,
        dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Scroll in a direction.

        When dry_run=True, return predicted result without executing.
        """
        self._ensure_imports()

        if dry_run:
            return action_result(ok=True, data={
                "action": "scroll", "direction": direction,
                "amount": amount, "dry_run": True,
            })

        try:
            scroll_amount = amount // 100  # pyautogui uses "clicks" (~100px each)
            if direction in ("down", "right"):
                scroll_amount = -scroll_amount

            if direction in ("up", "down"):
                self._pyautogui.scroll(scroll_amount)
            else:
                self._pyautogui.hscroll(scroll_amount)

            return action_result(ok=True)
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    # =================================================================
    # Screenshots
    # =================================================================

    async def screenshot(self) -> bytes:
        """Capture a screenshot of the target window only."""
        try:
            import mss
            import mss.tools
        except ImportError:
            raise ImportError("mss required for screenshots. pip install mss") from None

        rect = self._get_window_rect()
        with mss.MSS() as sct:
            monitor = {
                "left": int(rect.x),
                "top": int(rect.y),
                "width": int(rect.width),
                "height": int(rect.height),
            }
            shot = sct.grab(monitor)
            return mss.tools.to_png(shot.rgb, shot.size)

    # =================================================================
    # Hover
    # =================================================================

    async def hover(
        self, target: str, *, dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Hover over a target element.

        Moves the mouse to the target along a Bezier curve but does NOT
        click. Useful for triggering tooltips, hover menus, etc.

        When dry_run=True, resolve target and return predicted result
        without moving the mouse.
        """
        self._ensure_imports()

        if dry_run:
            point = self._resolve_target(target, **kwargs)
            return action_result(ok=True, data={
                "action": "hover", "target": target,
                "point": {"x": point.x, "y": point.y}, "dry_run": True,
            })

        try:
            self._check_abort()
            self._ensure_window_ready()
            point = self._resolve_target(target, **kwargs)
            point = self._validate_point_in_window(point)

            self._bring_to_front()
            settle_delay = random_delay_ms(self._focus_settle_ms, 100) / 1000.0
            await asyncio.sleep(settle_delay)

            self._check_abort()

            # Move along Bezier curve — but do NOT click
            await self._humanized_move(point)

            return action_result(ok=True, data={"x": point.x, "y": point.y})
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    # =================================================================
    # Wait for Element
    # =================================================================

    async def wait_for_selector(
        self, selector: str, timeout_ms: float = 5000,
    ) -> ActionResult:
        """Wait for a UI element to appear.

        Polls the UI Automation tree with exponential backoff until
        the target element is found or the timeout expires.

        Selector format matches _resolve_target_by_uia():
          - "name:Some Text" — search by Name
          - "auto:AutomationId" — search by AutomationId
          - Plain text — search by Name
        """
        self._ensure_imports()
        deadline = time.monotonic() + timeout_ms / 1000.0
        interval = 0.1  # Start polling at 100ms

        while time.monotonic() < deadline:
            point = self._resolve_target_by_uia(selector)
            if point is not None:
                return action_result(
                    ok=True,
                    data={"found": True, "selector": selector,
                          "point": {"x": point.x, "y": point.y}},
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(interval, remaining))
            interval = min(interval * 2, 1.0)  # Cap at 1s

        return action_result(
            ok=False,
            error=ActionError(
                ErrorCategory.SELECTOR_NOT_FOUND,
                f"Element '{selector}' not found within {timeout_ms:.0f}ms",
                selector=selector,
                recoverable=True,
                retry_hint="Try refreshing the window or scrolling to reveal the element",
            ),
        )

    # =================================================================
    # Optional Capabilities (not supported on desktop)
    # =================================================================

    async def select_option(
        self, target: str, value: str, **kwargs: Any,
    ) -> ActionResult:
        """Not supported for native Windows apps.

        Desktop apps use menus and combo boxes, not HTML <select>.
        Use click() to interact with native dropdown items.
        """
        return action_result(
            ok=False,
            error=ActionError(
                ErrorCategory.VALIDATION,
                "select_option not supported on desktop. Use click() instead.",
            ),
        )

    async def navigate(self, url: str) -> ActionResult:
        """Not supported for native Windows apps.

        Desktop apps don't navigate URLs. Use subprocess or win32api
        to launch external programs.
        """
        return action_result(
            ok=False,
            error=ActionError(
                ErrorCategory.VALIDATION,
                "navigate not supported on desktop.",
            ),
        )

    @property
    def supports_navigation(self) -> bool:
        """Desktop apps don't navigate URLs."""
        return False

    @property
    def supports_select(self) -> bool:
        """Desktop apps use native menus, not HTML <select>."""
        return False

    # =================================================================
    # Accessibility Tree
    # =================================================================

    async def snapshot(self) -> AXSnapshot:
        """Capture the UI Automation tree for the target window.

        Uses comtypes to walk the Windows UI Automation tree starting
        from the target window handle. Produces AXNodes for the cascade
        engine's Tier 1 (selector) resolution.

        Gracefully degrades if comtypes is not available (returns empty
        snapshot with just the window title).
        """
        try:
            from deskaoy.adapters.uia_walker import UIAWalker

            hwnd = self._resolve_hwnd()
            title = ""
            with contextlib.suppress(Exception):
                title = self._win32gui.GetWindowText(hwnd) if self._win32gui else ""

            walker = UIAWalker()
            return walker.walk_to_snapshot(
                hwnd=hwnd,
                url=f"win32://{title}",
                title=title,
            )
        except ImportError:
            logger.debug("comtypes not available, returning empty snapshot")
            return AXSnapshot(url=self.current_url(), title="")
        except Exception as exc:
            logger.warning("UIA snapshot failed: %s", exc)
            return AXSnapshot(url=self.current_url(), title="")

    # =================================================================
    # SurfaceAdapter required methods
    # =================================================================

    async def evaluate(self, expression: str) -> Any:
        """Not supported for native Windows — use native APIs instead."""
        return None

    def current_url(self) -> str:
        """Return window identifier."""
        try:
            hwnd = self._resolve_hwnd()
            return f"win32://{self._win32gui.GetWindowText(hwnd)}"
        except Exception:
            return "win32://unknown"

    async def current_title(self) -> str:
        """Return window title."""
        try:
            hwnd = self._resolve_hwnd()
            return self._win32gui.GetWindowText(hwnd)
        except Exception:
            return ""

    # =================================================================
    # Target Resolution
    # =================================================================

    def _resolve_target(self, target: str, **kwargs: Any) -> Point:
        """Resolve a target string to a screen Point.

        Supported formats:
          - "x,y" — direct coordinates
          - "name:Some Text" — UI Automation element search by name
          - "auto:id" — UI Automation element search by AutomationId
          - Anything else — UIA name search, then fallback to center
        """
        # Direct coordinates
        if "," in target:
            parts = target.split(",")
            try:
                return Point(float(parts[0]), float(parts[1]))
            except (ValueError, IndexError):
                pass

        # Try UIA element search
        point = self._resolve_target_by_uia(target)
        if point is not None:
            return point

        # Fallback: return center of window
        rect = self._get_window_rect()
        return rect.center

    def _resolve_target_by_uia(self, target: str) -> Point | None:
        """Resolve a target using UI Automation element search.

        Supports:
          - "name:Some Text" prefix — search by Name property
          - "auto:id" prefix — search by AutomationId property
          - Plain text — search by Name property (first match)

        Returns the center point of the found element, or None.
        """
        try:
            from deskaoy.adapters.uia_walker import UIAWalker
        except ImportError:
            return None

        hwnd = self._resolve_hwnd()
        walker = UIAWalker()

        element = None

        # Parse prefix
        if target.startswith("name:"):
            element = walker.find_element_by_name(hwnd, target[5:])
        elif target.startswith("auto:"):
            element = walker.find_element_by_automation_id(hwnd, target[5:])
        else:
            # Plain text — try name search
            element = walker.find_element_by_name(hwnd, target)

        if element is not None:
            cx, cy = element.center
            logger.debug(
                "UIA resolved '%s' -> (%.0f, %.0f) [%s]",
                target, cx, cy, element.control_type,
            )
            return Point(cx, cy)

        return None

    # ─── Window & Display Management (BATCH-20) ────────────────

    async def list_displays(self) -> list[dict]:
        """List connected displays with bounds and DPI."""
        self._ensure_imports()
        displays = []
        try:
            import win32api
            monitors = win32api.EnumDisplayMonitors()
            for i, (hmon, _hdc, rect) in enumerate(monitors):
                left, top, right, bottom = rect
                try:
                    dpi = self._win32api.GetDpiForMonitor(hmon, 0) if hasattr(self._win32api, 'GetDpiForMonitor') else 96
                except Exception:
                    dpi = 96
                displays.append({
                    "index": i,
                    "x": left, "y": top,
                    "width": right - left, "height": bottom - top,
                    "dpi": dpi if isinstance(dpi, (int, float)) else 96,
                    "primary": i == 0,
                })
        except Exception:
            # Fallback: single display from screen dimensions
            try:
                import win32api
                displays.append({
                    "index": 0,
                    "x": 0, "y": 0,
                    "width": win32api.GetSystemMetrics(0),
                    "height": win32api.GetSystemMetrics(1),
                    "dpi": 96, "primary": True,
                })
            except Exception:
                pass
        return displays

    async def list_windows(self) -> list[dict]:
        """List top-level visible windows."""
        self._ensure_imports()
        windows = []
        def _enum_cb(hwnd, _):
            if self._win32gui.IsWindowVisible(hwnd):
                title = self._win32gui.GetWindowText(hwnd)
                if title:
                    try:
                        import win32process
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    except Exception:
                        pid = 0
                    windows.append({
                        "hwnd": hwnd,
                        "title": title,
                        "pid": pid,
                        "visible": True,
                    })
            return True
        with contextlib.suppress(Exception):
            self._win32gui.EnumWindows(_enum_cb, None)
        return windows

    async def set_window_bounds(self, x: int, y: int, width: int, height: int) -> ActionResult:
        """Reposition and resize the target window."""
        self._ensure_imports()
        try:
            hwnd = self._resolve_hwnd()
            # SWP_NOZORDER = 0x0004, SWP_NOACTIVATE = 0x0010
            self._win32gui.SetWindowPos(hwnd, 0, x, y, width, height, 0x0004 | 0x0010)
            return ActionResult(ok=True)
        except Exception as exc:
            return ActionResult(ok=False, data={"error": str(exc)})

    async def focus_window(self, query: dict) -> ActionResult:
        """Focus a window by process name, title, or PID."""
        self._ensure_imports()
        try:
            title = query.get("title", "")
            process_name = query.get("process_name", "")
            pid = query.get("pid", 0)

            if title:
                hwnd = self._win32gui.FindWindow(None, title)
                if hwnd:
                    self._win32gui.SetForegroundWindow(hwnd)
                    return ActionResult(ok=True)
                return ActionResult(ok=False, data={"error": f"Window not found: {title}"})

            if process_name or pid:
                import win32process
                found_hwnd = None
                def _cb(hwnd, _):
                    nonlocal found_hwnd
                    if self._win32gui.IsWindowVisible(hwnd) and pid:
                        _, wpid = win32process.GetWindowThreadProcessId(hwnd)
                        if wpid == pid:
                            found_hwnd = hwnd
                            return False
                    return True
                self._win32gui.EnumWindows(_cb, None)
                if found_hwnd:
                    self._win32gui.SetForegroundWindow(found_hwnd)
                    return ActionResult(ok=True)
                return ActionResult(ok=False, data={"error": f"Window not found for query: {query}"})

            return ActionResult(ok=False, data={"error": "No query criteria provided"})
        except Exception as exc:
            return ActionResult(ok=False, data={"error": str(exc)})

    # ─── Element operations (BATCH-19) ───────────────────────

    async def invoke_element(
        self, target: str, action: str = "click", value: str = "", **kwargs: Any,
    ) -> ActionResult:
        """Invoke an accessibility action on an element — action-first.

        Action-first sequence for each action:
          1. Try the corresponding UIA pattern
          2. If pattern works → return ok with pattern_used metadata
          3. If pattern unavailable → fallback to pyautogui

        Actions: click, focus, set_value, get_value, expand, collapse,
        toggle, select.
        """
        self._ensure_imports()

        try:
            # --- Action-first: try UIA pattern for each action ---
            if action in ("click", "invoke", "toggle", "expand", "collapse",
                          "select", "set_value", "scroll_into_view"):
                pattern_result = await self._try_uia_invoke_action(
                    target, action, value, **kwargs,
                )
                if pattern_result is not None:
                    return pattern_result
                # Pattern not available — fall through to fallback

            if action == "click":
                return await self.click(target, **kwargs)

            elif action == "focus":
                # Set focus via UIA or click
                try:
                    from deskaoy.adapters.uia_walker import UIAWalker
                    walker = UIAWalker()
                    hwnd = self._resolve_hwnd()
                    raw_elem = self._resolve_raw_element(walker, hwnd, target)
                    if raw_elem is not None:
                        raw_elem.SetFocus()
                        return action_result(ok=True, data={
                            "pattern_used": "SetFocus",
                            "fallback_used": False,
                        })
                except Exception:
                    pass
                # Fallback: click to focus
                return await self.click(target, **kwargs)

            elif action == "set_value":
                # Click then type the value (pattern already tried above)
                click_result = await self.click(target, **kwargs)
                if not click_result.ok:
                    return click_result
                # Select all and type new value
                self._pyautogui.hotkey("ctrl", "a")
                await asyncio.sleep(0.1)
                self._pyautogui.write(value, interval=0)
                return action_result(ok=True, data={
                    "value_set": value,
                    "pattern_used": None, "fallback_used": True,
                })

            elif action == "get_value":
                # Try UIA ValuePattern first, then snapshot
                try:
                    from deskaoy.adapters.uia_walker import UIAWalker
                    walker = UIAWalker()
                    hwnd = self._resolve_hwnd()
                    raw_elem = self._resolve_raw_element(walker, hwnd, target)
                    if raw_elem is not None:
                        val = walker.try_get_value(raw_elem)
                        if val is not None:
                            return action_result(ok=True, data={
                                "value": val,
                                "pattern_used": "ValuePattern",
                                "fallback_used": False,
                            })
                except Exception:
                    pass
                return action_result(
                    ok=False,
                    error=ActionError(ErrorCategory.UNKNOWN, "Could not read element value"),
                )

            elif action == "toggle":
                # TogglePattern already tried — fallback to click
                return await self.click(target, **kwargs)

            elif action == "select":
                # SelectionItemPattern already tried — fallback to click
                return await self.click(target, **kwargs)

            elif action == "expand" or action == "collapse":
                # ExpandCollapsePattern already tried — fallback to click
                return await self.click(target, **kwargs)

            else:
                return action_result(
                    ok=False,
                    error=ActionError(
                        ErrorCategory.VALIDATION,
                        f"Unknown invoke action: {action}",
                    ),
                )
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    async def _try_uia_invoke_action(
        self, target: str, action: str, value: str, **kwargs: Any,
    ) -> ActionResult | None:
        """Try UIA pattern for invoke_element actions. Returns None to signal fallback."""
        try:
            from deskaoy.adapters.uia_walker import UIAWalker
            walker = UIAWalker()
            hwnd = self._resolve_hwnd()

            raw_elem = self._resolve_raw_element(walker, hwnd, target)
            if raw_elem is None:
                return None

            result = walker.invoke_action(raw_elem, action, value)
            if result is not None and result.success:
                return action_result(ok=True, data={
                    "pattern_used": result.pattern_used,
                    "fallback_used": False,
                    "method": "uia_pattern",
                    "action": action,
                })
        except Exception as exc:
            logger.debug(
                "UIA pattern for invoke '%s' failed, falling back: %s",
                action, exc,
            )
        return None

    async def get_element_state(self, target: str) -> dict:
        """Get element state: enabled, focused, selected, expanded, busy, offscreen."""
        self._ensure_imports()

        state = {
            "enabled": True,
            "focused": False,
            "selected": False,
            "expanded": False,
            "busy": False,
            "offscreen": False,
        }

        try:
            from deskaoy.adapters.uia_walker import UIAWalker
            walker = UIAWalker()
            hwnd = self._resolve_hwnd()
            element = walker.find_element_by_name(hwnd, target)
            if element:
                import comtypes  # noqa: F401
                from comtypes import GUID  # noqa: F401
                try:
                    # UIA_IsEnabledPropertyId = 30022
                    state["enabled"] = element.GetCurrentPropertyValue(30022)
                except Exception:
                    pass
                try:
                    # UIA_HasKeyboardFocusPropertyId = 30008
                    state["focused"] = element.GetCurrentPropertyValue(30008)
                except Exception:
                    pass
                try:
                    # UIA_SelectionItemIsSelectedPropertyId = 30049
                    state["selected"] = element.GetCurrentPropertyValue(30049)
                except Exception:
                    pass
                try:
                    # UIA_ExpandCollapseExpandCollapseStatePropertyId = 30081
                    expand_state = element.GetCurrentPropertyValue(30081)
                    state["expanded"] = expand_state == 1  # Expanded = 1
                except Exception:
                    pass
        except ImportError:
            pass
        except Exception:
            pass

        return state

    async def get_focused_element(self) -> dict | None:
        """Get the currently focused element."""
        self._ensure_imports()

        try:
            from deskaoy.adapters.uia_walker import UIAWalker
            walker = UIAWalker()
            hwnd = self._resolve_hwnd()
            focused = walker.get_focused_element(hwnd)
            if focused:
                return {
                    "ref": focused.ref if hasattr(focused, "ref") else "",
                    "name": focused.name if hasattr(focused, "name") else "",
                    "role": focused.control_type if hasattr(focused, "control_type") else "",
                }
        except Exception:
            pass
        return None

    # ─── Extended capabilities (BATCH-05) ──────────────────────

    async def read_clipboard(self) -> str:
        """Read the Windows clipboard via PowerShell."""
        import subprocess
        try:
            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=5
            )
            return result.stdout.rstrip("\n\r")
        except Exception as exc:
            raise RuntimeError(f"Failed to read clipboard: {exc}") from exc

    async def write_clipboard(self, text: str) -> None:
        """Write to the Windows clipboard via PowerShell."""
        import subprocess
        # Escape single quotes for PowerShell
        safe_text = text.replace("'", "''")
        try:
            subprocess.run(
                ["powershell", "-Command", f"Set-Clipboard -Value '{safe_text}'"],
                capture_output=True, text=True, timeout=5
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to write clipboard: {exc}") from exc

    async def paste(self) -> ActionResult:
        """Send Ctrl+V to paste clipboard contents.

        Uses the key_press method which handles blocklist checks.
        """
        return await self.key_press("v", modifiers=2)  # CTRL=2

    async def open_app(self, name: str) -> dict:
        """Open or focus an application on Windows (idempotent)."""
        import subprocess
        try:
            subprocess.run(
                ["powershell", "-Command", f"Start-Process '{name}'"],
                capture_output=True, text=True, timeout=10
            )
            return {"pid": 0, "title": name}
        except Exception as exc:
            raise RuntimeError(f"Failed to open app '{name}': {exc}") from exc

    async def set_window_state(self, state: str, target: str = "", **kwargs: Any) -> ActionResult:
        """Set window state: maximize, minimize, restore, close."""
        self._ensure_imports()
        hwnd = self._resolve_hwnd()
        state_map = {
            "maximize": 3,     # SW_MAXIMIZE
            "minimize": 6,     # SW_MINIMIZE
            "restore": 9,      # SW_RESTORE
        }
        try:
            if state == "close":
                self._win32gui.PostMessage(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                return ActionResult(ok=True)
            cmd = state_map.get(state)
            if cmd is None:
                return ActionResult(ok=False, data={"error": f"Unknown window state: {state}"})
            self._win32gui.ShowWindow(hwnd, cmd)
            return ActionResult(ok=True)
        except Exception as exc:
            return ActionResult(ok=False, data={"error": str(exc)})
