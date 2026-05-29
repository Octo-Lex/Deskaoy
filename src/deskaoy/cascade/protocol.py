"""SurfaceAdapter — platform contract for the cascade engine.

Implementations:
  - BrowserAdapter (Patchright/CDP)
  - MacOSAdapter (AXUIElement)
  - WindowsAdapter (UIA)
  - LinuxAdapter (AT-SPI)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from deskaoy.cascade.types import AXSnapshot
from deskaoy.results.types import ActionResult


class SurfaceAdapter(ABC):
    """Platform contract. Every surface adapter implements this interface.

    The cascade engine calls these methods without knowing whether it's
    talking to a browser, a native macOS app, or a Windows desktop app.
    """

    @abstractmethod
    async def click(self, target: str, *, dry_run: bool = False, **kwargs: Any) -> ActionResult:
        """Click on an element identified by selector/ref/coordinate hint.

        When dry_run=True, return predicted result without executing.
        """
        ...

    @abstractmethod
    async def fill(self, target: str, value: str, *, dry_run: bool = False, **kwargs: Any) -> ActionResult:
        """Fill a text input identified by target.

        When dry_run=True, return predicted result without executing.
        """
        ...

    @abstractmethod
    async def screenshot(self) -> bytes:
        """Capture a screenshot as PNG bytes."""
        ...

    @abstractmethod
    async def snapshot(self) -> AXSnapshot:
        """Capture the structural (accessibility) tree."""
        ...

    @abstractmethod
    async def evaluate(self, expression: str) -> Any:
        """Execute a platform-specific expression (JS, AppleScript, etc.)."""
        ...

    @abstractmethod
    async def key_press(self, key: str, modifiers: int = 0, *, dry_run: bool = False) -> ActionResult:
        """Press a key with optional modifiers.

        When dry_run=True, return predicted result without executing.
        """
        ...

    async def key_down(self, key: str, modifiers: int = 0, *, dry_run: bool = False) -> ActionResult:
        """Hold a key down (for chords, modifier holds, gaming input).

        Default implementation returns not-supported. Override in platform adapters.
        Must check key blocklist before executing.
        """
        return ActionResult(ok=False, data={"error": "key_down not supported"})

    async def key_up(self, key: str, modifiers: int = 0, *, dry_run: bool = False) -> ActionResult:
        """Release a held key.

        Default implementation returns not-supported. Override in platform adapters.
        """
        return ActionResult(ok=False, data={"error": "key_up not supported"})

    async def mouse_down(self, button: str = "left", *, dry_run: bool = False) -> ActionResult:
        """Press and hold a mouse button at the current position.

        Default implementation returns not-supported. Override in platform adapters.
        """
        return ActionResult(ok=False, data={"error": "mouse_down not supported"})

    async def mouse_up(self, button: str = "left", *, dry_run: bool = False) -> ActionResult:
        """Release a held mouse button.

        Default implementation returns not-supported. Override in platform adapters.
        """
        return ActionResult(ok=False, data={"error": "mouse_up not supported"})

    async def mouse_drag(self, start: str, end: str, *, button: str = "left", dry_run: bool = False, **kwargs: Any) -> ActionResult:
        """Drag from start to end coordinates.

        Coordinates as "x,y" strings. Default returns not-supported.
        Override in platform adapters that support drag.
        """
        return ActionResult(ok=False, data={"error": "mouse_drag not supported"})

    @abstractmethod
    async def scroll(self, direction: str, amount: int = 500, *, dry_run: bool = False) -> ActionResult:
        """Scroll in a direction by amount pixels.

        When dry_run=True, return predicted result without executing.
        """
        ...

    @abstractmethod
    async def type_text(self, text: str, delay_ms: float = 0, *, dry_run: bool = False) -> ActionResult:
        """Type text character by character with optional delay.

        When dry_run=True, return predicted result without executing.
        """
        ...

    @abstractmethod
    def current_url(self) -> str:
        """Return the current URL/focus identifier."""
        ...

    @abstractmethod
    async def current_title(self) -> str:
        """Return the current window/page title."""
        ...

    # --- Optional capabilities ---

    async def select_option(self, target: str, value: str, **kwargs: Any) -> ActionResult:
        """Select an option in a dropdown. Not all surfaces support this."""
        return ActionResult(ok=False, data={"error": "select_option not supported"})

    async def navigate(self, url: str) -> ActionResult:
        """Navigate to a URL. Only meaningful for browser surfaces."""
        return ActionResult(ok=False, data={"error": "navigate not supported"})

    async def hover(self, target: str, **kwargs: Any) -> ActionResult:
        """Hover over an element."""
        return ActionResult(ok=False, data={"error": "hover not supported"})

    async def wait_for_selector(self, selector: str, timeout_ms: float = 5000) -> ActionResult:
        """Wait for an element to appear."""
        return ActionResult(ok=True)

    # --- Extended capabilities (BATCH-05) ---

    async def read_clipboard(self) -> str:
        """Read the system clipboard. Raises NotImplementedError if unsupported."""
        raise NotImplementedError(f"{type(self).__name__} does not support read_clipboard")

    async def write_clipboard(self, text: str) -> None:
        """Write to the system clipboard. Raises NotImplementedError if unsupported."""
        raise NotImplementedError(f"{type(self).__name__} does not support write_clipboard")

    async def paste(self) -> ActionResult:
        """Send Ctrl+V (Cmd+V on macOS) to paste clipboard contents.

        Default implementation uses key_press('v', modifiers=CTRL).
        Override for platform-specific paste behavior.
        """
        # CTRL modifier = bitmask 2
        return await self.key_press("v", modifiers=2)

    async def open_app(self, name: str) -> dict:
        """Open/focus an application. Returns {pid, title} if supported."""
        raise NotImplementedError(f"{type(self).__name__} does not support open_app")

    async def invoke_element(self, target: str, action: str = "click", value: str = "", **kwargs: Any) -> ActionResult:
        """Invoke an accessibility action on an element.

        Actions: click, focus, set_value, get_value, expand, collapse, toggle, select.
        """
        # Default: fall back to click for 'click' action
        if action == "click":
            return await self.click(target)
        return ActionResult(ok=False, data={"error": f"invoke_element({action}) not supported"})

    async def set_window_state(self, state: str, target: str = "", **kwargs: Any) -> ActionResult:
        """Set window state: maximize, minimize, restore, close."""
        return ActionResult(ok=False, data={"error": f"set_window_state({state}) not supported"})

    async def get_focused_element(self) -> dict | None:
        """Get the currently focused element, or None if unknown."""
        return None

    async def get_element_state(self, target: str) -> dict:
        """Get element state: enabled, focused, selected, expanded, etc."""
        return {}

    # --- Visual feedback hooks (BATCH-32) ---

    def set_feedback_engine(self, engine: Any) -> None:
        """Attach a visual feedback engine (FeedbackEngine). None disables feedback."""
        self._feedback_engine = engine

    def get_feedback_engine(self) -> Any:
        """Return the attached feedback engine, or None if not set."""
        return getattr(self, '_feedback_engine', None)

    async def list_displays(self) -> list[dict]:
        """List connected displays with bounds and DPI.

        Returns list of dicts with keys: x, y, width, height, dpi, primary.
        """
        return []

    async def list_windows(self) -> list[dict]:
        """List top-level visible windows.

        Returns list of dicts with keys: hwnd, title, pid, visible.
        """
        return []

    async def set_window_bounds(self, x: int, y: int, width: int, height: int) -> ActionResult:
        """Reposition and resize the target window."""
        return ActionResult(ok=False, data={"error": "set_window_bounds not supported"})

    async def focus_window(self, query: dict) -> ActionResult:
        """Focus a window by process name, title, or PID.

        Query keys: process_name, title, pid.
        """
        return ActionResult(ok=False, data={"error": "focus_window not supported"})

    @property
    def supports_navigation(self) -> bool:
        """Whether this surface supports URL navigation."""
        return False

    @property
    def supports_select(self) -> bool:
        """Whether this surface supports dropdown selection."""
        return False
