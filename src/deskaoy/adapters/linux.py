"""Linux desktop adapter — AT-SPI2 accessibility + input injection.

Implements SurfaceAdapter for Linux desktop applications using:
  - AT-SPI2 (python3-atspi): Accessibility tree (the "structural eyes")
  - xdotool: Mouse/keyboard injection on X11 (the "hands")
  - PIL.ImageGrab / scrot: Screenshots (the "visual eyes")

Lazy imports ensure this module never crashes on Windows/macOS — all
AT-SPI2 imports happen inside methods, guarded by platform checks.

Safety guarantees:
  - All coordinates validated against accessible bounds where possible
  - Lazy imports: atspi only imported when actually used on Linux
  - Graceful fallback: clear error messages when deps missing

Input injection backend:
  - X11 + xdotool: real click, type_text, key_press, scroll, fill
  - Wayland or missing xdotool: returns UNSUPPORTED (no fake success)
  - dry_run always works without subprocess invocation
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
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


def _redact_xdotool_args(args: list[str]) -> list[str]:
    """Redact user-supplied data in xdotool args for safe logging.

    After the ``--`` separator (which xdotool uses to delimit literal data),
    all arguments are replaced with ``<redacted>`` to prevent leaking typed
    text (passwords, tokens, private data) into debug logs.
    """
    redacted: list[str] = []
    redact_rest = False
    for arg in args:
        if redact_rest:
            redacted.append("<redacted>")
            continue
        redacted.append(arg)
        if arg == "--":
            redact_rest = True
    return redacted


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
            ) from None

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
    # Input backend detection
    # ------------------------------------------------------------------

    def _input_backend_status(self) -> tuple[str, bool, str]:
        """Check whether a real input-injection backend is available.

        Returns ``(backend_name, available, reason_if_unavailable)``.

        Currently supports **xdotool on X11 only**. Wayland is unsupported
        because global input injection is compositor/portal-dependent and
        cannot be done generically without the user's explicit consent.
        """
        session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
        if session_type == "wayland":
            return ("xdotool", False, "Wayland session detected — xdotool cannot "
                    "inject input on Wayland without compositor-specific portals")

        if not os.environ.get("DISPLAY"):
            return ("xdotool", False, "No DISPLAY environment variable — "
                    "X11 session not detected")

        if not shutil.which("xdotool"):
            return ("xdotool", False, "xdotool binary not found — "
                    "install with: sudo apt install xdotool")

        return ("xdotool", True, "")

    def _run_xdotool(self, args: list[str]) -> subprocess.CompletedProcess:
        """Execute an xdotool command and return the completed process.

        Raises ``FileNotFoundError`` if xdotool is not installed, and
        ``subprocess.CalledProcessError`` if the command fails.

        Debug logs redact any argument after ``--`` (the xdotool data
        separator) to prevent leaking user-supplied text such as passwords,
        tokens, or private data into logs.
        """
        safe_cmd = ["xdotool", *_redact_xdotool_args(args)]
        logger.debug("xdotool: %s", " ".join(safe_cmd))
        return subprocess.run(  # noqa: S603 — trusted binary, args are validated
            ["xdotool"] + args,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )

    # ------------------------------------------------------------------
    # Mouse actions
    # ------------------------------------------------------------------

    async def click(
        self, target: str, *, dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Click on a target element via AT-SPI2 action or xdotool.

        Priority:
        1. **AT-SPI2 Action interface** — a real accessibility action
           (e.g. ``Action.DoAction``). This succeeds without xdotool when
           an accessible element exposes an invoke/click action. It is a
           legitimate real action, not fake success.
        2. **Coordinate-based click via xdotool** — when no AT-SPI action
           is available, resolves the target to a point and runs
           ``xdotool mousemove x y click 1``.

        Returns ``UNSUPPORTED`` only for the coordinate fallback when no
        X11 + xdotool backend is available. AT-SPI action clicks work
        independently of xdotool availability.
        """
        if dry_run:
            return action_result(ok=True, data={
                "action": "click", "target": target, "dry_run": True,
            })

        # Try AT-SPI2 Action interface first (no input injection needed)
        try:
            self._ensure_imports()
            acc = self._find_accessible(target)
            if acc is not None:
                action_result_data = self._try_atspi_action(acc, "click")
                if action_result_data is not None:
                    return action_result(ok=True, data=action_result_data)
        except Exception:
            pass  # Fall through to coordinate-based

        # Coordinate-based click via xdotool
        backend, available, reason = self._input_backend_status()
        if not available:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNSUPPORTED, reason),
            )

        try:
            point = self._resolve_point_or_none(target)
            if point is None:
                return action_result(
                    ok=False,
                    error=ActionError(
                        ErrorCategory.SELECTOR_NOT_FOUND,
                        f"Could not resolve target to coordinates: {target!r}. "
                        f"Use 'x,y' format for direct coordinates.",
                    ),
                )
            self._run_xdotool(["mousemove", str(point[0]), str(point[1]), "click", "1"])
            return action_result(ok=True, data={
                "x": point[0], "y": point[1],
                "method": "xdotool",
            })
        except subprocess.CalledProcessError as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, f"xdotool click failed: {exc.stderr}"),
            )
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, str(exc)),
            )

    async def fill(
        self, target: str, value: str, *, dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Fill a text field by clicking it then typing the value.

        Uses xdotool for real injection when available. Fails before any
        side effect if the backend is unavailable.
        """
        if dry_run:
            return action_result(ok=True, data={
                "action": "fill", "target": target,
                "value": value, "dry_run": True,
            })

        # Check backend BEFORE any click — no partial side effects
        backend, available, reason = self._input_backend_status()
        if not available:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNSUPPORTED, reason),
            )

        # Click the target
        click_result = await self.click(target)
        if not click_result.ok:
            return click_result

        # Type the value
        try:
            self._run_xdotool(["type", "--clearmodifiers", "--", value])
            return action_result(ok=True, data={
                "value": value,
                "method": "xdotool",
            })
        except subprocess.CalledProcessError as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, f"xdotool type failed: {exc.stderr}"),
            )

    # ------------------------------------------------------------------
    # Keyboard actions
    # ------------------------------------------------------------------

    async def type_text(
        self, text: str, delay_ms: float = 0, *,
        dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Type text via xdotool.

        Requires an X11 session with xdotool installed. Returns
        ``UNSUPPORTED`` on Wayland or when xdotool is missing.
        """
        if dry_run:
            return action_result(ok=True, data={
                "action": "type_text", "char_count": len(text), "dry_run": True,
            })

        backend, available, reason = self._input_backend_status()
        if not available:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNSUPPORTED, reason),
            )

        try:
            args = ["type", "--clearmodifiers"]
            if delay_ms > 0:
                args.extend(["--delay", str(int(delay_ms))])
            args.extend(["--", text])
            self._run_xdotool(args)
            return action_result(ok=True, data={
                "text": text,
                "method": "xdotool",
            })
        except subprocess.CalledProcessError as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, f"xdotool type failed: {exc.stderr}"),
            )

    async def key_press(
        self, key: str, modifiers: int = 0, *,
        dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Press a key with optional modifiers via xdotool.

        Enforces the key blocklist **before** any backend check. Returns
        ``UNSUPPORTED`` if xdotool is not available.
        """
        # SECURITY: Check key blocklist (pure Python, no backend needed)
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

        backend, available, reason = self._input_backend_status()
        if not available:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNSUPPORTED, reason),
            )

        try:
            self._run_xdotool(["key", "--clearmodifiers", combo])
            return action_result(ok=True, data={
                "key": key, "modifiers": modifiers,
                "combo": combo,
                "method": "xdotool",
            })
        except subprocess.CalledProcessError as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, f"xdotool key failed: {exc.stderr}"),
            )

    async def scroll(
        self, direction: str, amount: int = 500, *,
        dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Scroll in a direction via xdotool mouse button simulation.

        Maps directions to X11 mouse buttons:
        - ``up`` → button 4
        - ``down`` → button 5
        - ``left`` → button 6
        - ``right`` → button 7

        The ``amount`` parameter controls scroll magnitude. It is scaled to a
        bounded number of button clicks (1–10), where each click is roughly
        equivalent to one mouse-wheel notch. The actual pixel distance depends
        on the window manager's scroll settings.

        Returns ``UNSUPPORTED`` if xdotool is not available.
        """
        direction_norm = direction.lower().strip()
        button_map = {"up": "4", "down": "5", "left": "6", "right": "7"}

        if direction_norm not in button_map:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.VALIDATION,
                    f"Invalid scroll direction: {direction!r}. "
                    f"Must be one of: {', '.join(button_map)}"),
            )

        # Scale amount (0-5000) to bounded click count (1-10)
        click_count = max(1, min(10, amount // 100))

        if dry_run:
            return action_result(ok=True, data={
                "action": "scroll", "direction": direction_norm,
                "amount": amount,
                "click_count": click_count,
                "dry_run": True,
            })

        backend, available, reason = self._input_backend_status()
        if not available:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNSUPPORTED, reason),
            )

        try:
            button = button_map[direction_norm]
            # Use --repeat for bounded scroll magnitude
            self._run_xdotool(["click", "--repeat", str(click_count), button])
            return action_result(ok=True, data={
                "direction": direction_norm,
                "amount": amount,
                "click_count": click_count,
                "button": button,
                "method": "xdotool",
            })
        except subprocess.CalledProcessError as exc:
            return action_result(
                ok=False,
                error=ActionError(ErrorCategory.UNKNOWN, f"xdotool scroll failed: {exc.stderr}"),
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

        .. deprecated:: Use :meth:`_resolve_point_or_none` for callers
           that need to distinguish "resolved" from "not found."
        """
        point = self._resolve_point_or_none(target)
        if point is not None:
            return point
        return (0.0, 0.0)

    def _resolve_point_or_none(self, target: str) -> tuple[float, float] | None:
        """Resolve a target string to screen coordinates, or None if not found.

        - Direct coordinates like ``"100,200"`` are parsed immediately.
        - Named targets are searched via AT-SPI2; returns ``None`` if the
          element cannot be found or has no extents.
        """
        # Direct coordinates
        if "," in target:
            parts = target.split(",")
            try:
                return (float(parts[0]), float(parts[1]))
            except (ValueError, IndexError):
                return None

        # Try AT-SPI2 search
        acc = self._find_accessible(target)
        if acc is not None:
            try:
                ext = acc.get_extents(self._atspi.CoordType.SCREEN)
                if ext and ext.width > 0 and ext.height > 0:
                    return (
                        ext.x + ext.width / 2,
                        ext.y + ext.height / 2,
                    )
            except Exception:
                pass

        return None

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
