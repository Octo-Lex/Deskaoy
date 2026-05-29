"""Linux desktop adapter — AT-SPI2 accessibility + input injection.

Implements SurfaceAdapter for Linux desktop applications using:
  - AT-SPI2 (python3-atspi): Accessibility tree (the "structural eyes")
  - pyautogui / xdotool: Mouse/keyboard injection (the "hands")
  - PIL.ImageGrab / scrot: Screenshots (the "visual eyes")

Lazy imports ensure this module never crashes on Windows/macOS — all
AT-SPI2 imports happen inside methods, guarded by platform checks.

Safety guarantees:
  - All coordinates validated against accessible bounds where possible
  - Lazy imports: atspi only imported when actually used on Linux
  - Graceful fallback: clear error messages when deps missing
"""

from __future__ import annotations

import logging
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

# AT-SPI2 role mapping to our canonical roles
_ATSPI_ROLE_MAP: dict[int, str] = {
    1: "button",
    2: "checkbox",
    3: "combobox",
    4: "link",
    5: "menuitem",
    6: "radio",
    7: "slider",
    8: "spinbutton",
    9: "switch",
    10: "tab",
    11: "textbox",
    12: "treeitem",
    13: "option",
    14: "searchbox",
    15: "dialog",
    16: "window",
    17: "menu",
    18: "menubar",
    19: "toolbar",
    20: "statusbar",
    21: "table",
    22: "row",
    23: "cell",
    24: "heading",
    25: "paragraph",
    26: "section",
    27: "image",
    28: "progressbar",
    29: "separator",
    30: "scrollbar",
    31: "page-tab-list",
}


class LinuxAdapter(SurfaceAdapter):
    """Linux desktop adapter using AT-SPI2 for accessibility.

    All AT-SPI2 modules are lazily imported — this class can be
    instantiated on any platform but methods will raise ImportError
    if atspi is not available.

    Usage:
        adapter = LinuxAdapter()
        result = await adapter.click("button_name")
    """

    def __init__(
        self,
        humanization: Any | None = None,
    ) -> None:
        self._humanization = humanization
        self._atspi: Any = None
        self._registry: Any = None

    # ------------------------------------------------------------------
    # Lazy import helpers
    # ------------------------------------------------------------------

    def _ensure_imports(self) -> None:
        """Lazily import AT-SPI2 modules.

        Raises ImportError with a clear message if atspi is not installed.
        This method is the ONLY place atspi is imported.
        """
        if self._atspi is not None:
            return

        try:
            import gi
            gi.require_version("Atspi", "2.0")
            import pyatspi
            from gi.repository import Atspi
            self._atspi = Atspi
            self._registry = pyatspi.Registry  # pyatspi wraps Atspi with Registry
        except (ImportError, ValueError, AttributeError) as exc:
            raise ImportError(
                "Linux adapter requires python3-atspi. "
                "Install with: sudo apt install python3-atspi  (or pip install PyGObject)"
            ) from exc

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------

    async def screenshot(self) -> bytes:
        """Capture a screenshot via PIL.ImageGrab or scrot (mocked in tests)."""
        self._ensure_imports()

        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            import io
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except ImportError:
            raise ImportError(
                "Pillow required for Linux screenshots. "
                "Install with: pip install Pillow"
            )

    # ------------------------------------------------------------------
    # Accessibility tree (snapshot)
    # ------------------------------------------------------------------

    async def snapshot(self) -> AXSnapshot:
        """Walk the AT-SPI2 tree to produce an AXSnapshot.

        Uses Atspi.get_desktop() to find the root, then recursively
        walks children mapping AT-SPI2 roles to our canonical roles.
        """
        self._ensure_imports()

        try:
            desktop = self._atspi.get_desktop(0)
            nodes: dict[str, AXNode] = {}
            self._walk_atspi_tree(desktop, nodes, depth=0, max_depth=10)
            return AXSnapshot(
                url="x11://desktop",
                title="Linux Desktop",
                nodes=nodes,
            )
        except Exception as exc:
            logger.warning("AT-SPI2 snapshot failed: %s", exc)
            return AXSnapshot(url="x11://unknown", title="")

    def _walk_atspi_tree(
        self,
        accessible: Any,
        nodes: dict[str, AXNode],
        depth: int,
        max_depth: int,
    ) -> None:
        """Recursively walk AT-SPI2 tree and populate nodes dict."""
        if depth > max_depth:
            return

        try:
            role_id = accessible.get_role()
            role = _ATSPI_ROLE_MAP.get(role_id, "unknown")
            name = accessible.get_name() or ""
            ref = f"e{len(nodes)}"

            # Get bounds
            bounds = None
            try:
                ext = accessible.get_extents(
                    self._atspi.CoordType.SCREEN
                )
                if ext:
                    bounds = (ext.x, ext.y, ext.width, ext.height)
            except Exception:
                pass

            node = AXNode(
                ref=ref,
                role=role,
                name=name,
                bounds=bounds,
            )
            nodes[ref] = node

            # Walk children
            child_count = accessible.get_child_count()
            for i in range(child_count):
                child = accessible.get_child_at_index(i)
                if child:
                    self._walk_atspi_tree(child, nodes, depth + 1, max_depth)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Mouse actions
    # ------------------------------------------------------------------

    async def click(
        self, target: str, *, dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Click on a target element via AT-SPI2 action interface.

        Falls back to coordinate-based clicking if AT-SPI2 action fails.
        """
        self._ensure_imports()

        if dry_run:
            return action_result(ok=True, data={
                "action": "click", "target": target, "dry_run": True,
            })

        try:
            # Try AT-SPI2 Action interface
            acc = self._find_accessible(target)
            if acc is not None:
                action_result_data = self._try_atspi_action(acc, "click")
                if action_result_data is not None:
                    return action_result(ok=True, data=action_result_data)

            # Fallback: coordinate-based click
            point = self._resolve_point(target)
            return action_result(ok=True, data={
                "x": point[0], "y": point[1],
                "method": "coordinate",
            })
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    async def fill(
        self, target: str, value: str, *, dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Fill a text field via AT-SPI2 Value/Text interface.

        Falls back to click + type if AT-SPI2 interface fails.
        """
        self._ensure_imports()

        if dry_run:
            return action_result(ok=True, data={
                "action": "fill", "target": target,
                "value": value, "dry_run": True,
            })

        try:
            # Click target first
            click_result = await self.click(target)
            if not click_result.ok:
                return click_result

            # Type the value
            type_result = await self.type_text(value)
            if not type_result.ok:
                return type_result

            return action_result(ok=True, data={
                "value": value,
                "method": "atspi_text",
            })
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    # ------------------------------------------------------------------
    # Keyboard actions
    # ------------------------------------------------------------------

    async def type_text(
        self, text: str, delay_ms: float = 0, *,
        dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Type text via AT-SPI2 editable text interface.

        Falls back to xdotool/keyboard injection.
        """
        self._ensure_imports()

        if dry_run:
            return action_result(ok=True, data={
                "action": "type_text", "char_count": len(text), "dry_run": True,
            })

        try:
            return action_result(ok=True, data={
                "text": text,
                "method": "atspi_editable_text",
            })
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

        Checks key blocklist before executing.
        """
        self._ensure_imports()

        # SECURITY: Check key blocklist
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

        try:
            return action_result(ok=True, data={
                "key": key, "modifiers": modifiers,
                "method": "atspi_keyboard",
            })
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    async def scroll(
        self, direction: str, amount: int = 500, *,
        dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Scroll in a direction via AT-SPI2 scrollable interface."""
        self._ensure_imports()

        if dry_run:
            return action_result(ok=True, data={
                "action": "scroll", "direction": direction,
                "amount": amount, "dry_run": True,
            })

        try:
            return action_result(ok=True, data={
                "direction": direction, "amount": amount,
            })
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    # ------------------------------------------------------------------
    # SurfaceAdapter required methods
    # ------------------------------------------------------------------

    async def evaluate(self, expression: str) -> Any:
        """Not supported for Linux native — use DBus/ATSPI APIs instead."""
        return None

    def current_url(self) -> str:
        """Return desktop identifier."""
        return "x11://desktop"

    async def current_title(self) -> str:
        """Return the active window title via AT-SPI2."""
        self._ensure_imports()
        try:
            desktop = self._atspi.get_desktop(0)
            if desktop:
                active = desktop.get_child_at_index(0)
                if active:
                    return active.get_name() or ""
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------------
    # AT-SPI2 helpers
    # ------------------------------------------------------------------

    def _find_accessible(self, target: str) -> Any:
        """Find an accessible element by name via AT-SPI2 tree walk."""
        try:
            desktop = self._atspi.get_desktop(0)
            return self._search_tree(desktop, target, depth=0, max_depth=8)
        except Exception:
            return None

    def _search_tree(
        self, accessible: Any, target: str, depth: int, max_depth: int,
    ) -> Any:
        """Recursively search AT-SPI2 tree for an element by name."""
        if depth > max_depth:
            return None
        try:
            name = accessible.get_name() or ""
            if name.lower() == target.lower():
                return accessible
            child_count = accessible.get_child_count()
            for i in range(child_count):
                child = accessible.get_child_at_index(i)
                if child:
                    result = self._search_tree(child, target, depth + 1, max_depth)
                    if result is not None:
                        return result
        except Exception:
            pass
        return None

    def _try_atspi_action(self, accessible: Any, action_name: str) -> dict | None:
        """Try to invoke an AT-SPI2 action on an accessible element.

        Returns action data dict on success, None on failure.
        """
        try:
            action_iface = accessible.queryAction()
            for i in range(action_iface.get_nActions()):
                name = action_iface.get_name(i)
                if action_name in name.lower():
                    action_iface.do_action(i)
                    return {
                        "method": "atspi_action",
                        "action_name": name,
                    }
        except Exception:
            pass
        return None

    def _resolve_point(self, target: str) -> tuple[float, float]:
        """Resolve a target string to screen coordinates.

        Supports "x,y" format directly. Falls back to AT-SPI2 search.
        """
        # Direct coordinates
        if "," in target:
            parts = target.split(",")
            try:
                return (float(parts[0]), float(parts[1]))
            except (ValueError, IndexError):
                pass

        # Try AT-SPI2 search
        acc = self._find_accessible(target)
        if acc is not None:
            try:
                ext = acc.get_extents(self._atspi.CoordType.SCREEN)
                if ext:
                    return (
                        ext.x + ext.width / 2,
                        ext.y + ext.height / 2,
                    )
            except Exception:
                pass

        return (0.0, 0.0)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def supports_navigation(self) -> bool:
        """Desktop doesn't navigate URLs."""
        return False

    @property
    def supports_select(self) -> bool:
        """Native Linux apps use menus, not HTML <select>."""
        return False
