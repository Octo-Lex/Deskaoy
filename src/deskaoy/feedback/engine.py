"""FeedbackEngine — tkinter-based visual feedback overlay.

Provides optional visual feedback during desktop automation:
  - Click ripple animation at click points
  - Highlight rectangle around elements
  - Scroll direction indicator
  - Fading cursor trail between mouse positions

All overlays are rendered on a transparent, always-on-top tkinter
window that does NOT steal focus.  The overlay is short-lived
(animations complete in < 500 ms) so it never blocks the user.

Design constraints:
  - HB-01: Opt-in only — FeedbackEngine is a no-op until enabled.
  - HB-02: Overlay must not shift automation coordinates (transparent,
    click-through where possible).
  - No external dependencies — uses only tkinter (stdlib).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class ScrollDirection(StrEnum):
    """Scroll direction for indicator overlay."""
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"


@dataclass
class Bounds:
    """Rectangle bounds for highlight overlay."""
    x: int
    y: int
    width: int
    height: int


@dataclass
class TrailPoint:
    """Single point in a cursor trail with opacity (0.0–1.0)."""
    x: int
    y: int
    opacity: float = 1.0


@dataclass
class FeedbackConfig:
    """Configuration for visual feedback rendering."""
    # Ripple settings
    ripple_radius: int = 20
    ripple_duration_ms: int = 400
    ripple_color: str = "#4A90D9"

    # Highlight settings
    highlight_border_width: int = 3
    highlight_duration_ms: int = 500
    highlight_color: str = "#FFB347"

    # Scroll indicator settings
    scroll_duration_ms: int = 300
    scroll_color: str = "#7BC67E"

    # Trail settings
    trail_duration_ms: int = 500
    trail_color: str = "#B388FF"
    trail_max_points: int = 50
    trail_line_width: int = 2

    # Global
    enabled: bool = False  # HB-01: off by default


# ---------------------------------------------------------------------------
# FeedbackEngine
# ---------------------------------------------------------------------------

class FeedbackEngine:
    """Visual feedback overlay engine using tkinter.

    All visual methods are no-ops when ``enabled`` is False (HB-01).
    When enabled, animations are rendered on a transparent, always-on-top
    overlay that does not steal focus (HB-02).

    Usage::

        engine = FeedbackEngine()
        engine.enabled = True  # opt-in

        engine.show_click_ripple(500, 300)
        engine.show_highlight(Bounds(100, 200, 300, 50))
        engine.show_scroll_indicator(ScrollDirection.DOWN)
        engine.show_cursor_trail([TrailPoint(100, 100), TrailPoint(200, 200)])
    """

    def __init__(self, config: FeedbackConfig | None = None) -> None:
        self._config = config or FeedbackConfig()
        self._tk_available = self._check_tkinter()

        # Track active animations for cleanup
        self._active_animations: int = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether visual feedback is active (HB-01: default False)."""
        return self._config.enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._config.enabled = value

    @property
    def config(self) -> FeedbackConfig:
        """Current feedback configuration."""
        return self._config

    @property
    def active_animations(self) -> int:
        """Number of currently running animations (for diagnostics)."""
        return self._active_animations

    # ------------------------------------------------------------------
    # Public API — visual feedback methods
    # ------------------------------------------------------------------

    def show_click_ripple(self, x: int, y: int) -> bool:
        """Show a brief expanding-circle ripple at (x, y).

        Returns True if animation was started, False if feedback is
        disabled or tkinter is unavailable.
        """
        if not self._config.enabled or not self._tk_available:
            return False

        logger.debug("click_ripple at (%d, %d)", x, y)
        self._start_animation(
            "ripple", x, y,
            duration_ms=self._config.ripple_duration_ms,
        )
        return True

    def show_highlight(self, bounds: Bounds) -> bool:
        """Show a highlight rectangle around *bounds*.

        Returns True if animation was started, False otherwise.
        """
        if not self._config.enabled or not self._tk_available:
            return False

        logger.debug(
            "highlight at (%d, %d, %d, %d)",
            bounds.x, bounds.y, bounds.width, bounds.height,
        )
        self._start_animation(
            "highlight", bounds.x, bounds.y,
            extra={
                "width": bounds.width,
                "height": bounds.height,
                "border_width": self._config.highlight_border_width,
                "color": self._config.highlight_color,
            },
            duration_ms=self._config.highlight_duration_ms,
        )
        return True

    def show_scroll_indicator(self, direction: ScrollDirection) -> bool:
        """Show a brief scroll-direction arrow indicator.

        Returns True if animation was started, False otherwise.
        """
        if not self._config.enabled or not self._tk_available:
            return False

        logger.debug("scroll_indicator: %s", direction.value)
        self._start_animation(
            "scroll", 0, 0,
            extra={"direction": direction.value},
            duration_ms=self._config.scroll_duration_ms,
        )
        return True

    def show_cursor_trail(self, points: list[TrailPoint]) -> bool:
        """Show a fading cursor trail through *points*.

        Returns True if animation was started, False otherwise.
        """
        if not self._config.enabled or not self._tk_available:
            return False

        # Clamp to max points
        if len(points) > self._config.trail_max_points:
            points = points[-self._config.trail_max_points:]

        if not points:
            return False

        logger.debug("cursor_trail: %d points", len(points))
        self._start_animation(
            "trail", 0, 0,
            extra={
                "points": [(p.x, p.y, p.opacity) for p in points],
                "color": self._config.trail_color,
                "line_width": self._config.trail_line_width,
            },
            duration_ms=self._config.trail_duration_ms,
        )
        return True

    # ------------------------------------------------------------------
    # Feedback hooks for SurfaceAdapter integration
    # ------------------------------------------------------------------

    def on_before_click(self, x: int, y: int) -> None:
        """Hook called before a click action — shows ripple at target."""
        self.show_click_ripple(x, y)

    def on_after_click(self, x: int, y: int) -> None:
        """Hook called after a click action — can show completion indicator."""
        # Currently no-op; reserved for future expansion (e.g. success pulse)
        pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_tkinter(self) -> bool:
        """Check if tkinter is available (may not be on headless Linux)."""
        try:
            import tkinter  # noqa: F401
            return True
        except ImportError:
            logger.debug("tkinter not available — visual feedback disabled")
            return False

    def _start_animation(
        self,
        kind: str,
        x: int,
        y: int,
        *,
        duration_ms: int = 400,
        extra: dict | None = None,
    ) -> None:
        """Spawn an overlay animation in a background thread.

        Each animation runs in its own daemon thread so it never blocks
        the main automation loop.
        """
        with self._lock:
            self._active_animations += 1

        thread = threading.Thread(
            target=self._run_overlay,
            args=(kind, x, y, duration_ms, extra),
            daemon=True,
            name=f"feedback-{kind}-{time.monotonic_ns()}",
        )
        thread.start()

    def _run_overlay(
        self,
        kind: str,
        x: int,
        y: int,
        duration_ms: int,
        extra: dict | None,
    ) -> None:
        """Run a tkinter overlay in a background thread.

        Creates a transparent, topmost window, draws the requested
        animation, then destroys the window after *duration_ms*.
        """
        import tkinter as tk

        try:
            root = tk.Tk()
            root.overrideredirect(True)  # No window decorations
            root.attributes("-topmost", True)  # Always on top
            root.attributes("-alpha", 0.7)  # Semi-transparent

            # Try to make click-through (Windows only)
            try:
                # -transparentcolor makes a color fully transparent to clicks
                root.attributes("-transparentcolor", "white")
            except (tk.TclError, Exception):
                pass

            # Set size based on animation type
            if kind == "ripple":
                size = self._config.ripple_radius * 2 + 20
                root.geometry(f"{size}x{size}+{x - size // 2}+{y - size // 2}")
                canvas = tk.Canvas(
                    root, width=size, height=size,
                    bg="white", highlightthickness=0,
                )
                canvas.pack()
                self._draw_ripple(canvas, size, size // 2, size // 2)

            elif kind == "highlight":
                w = extra.get("width", 100) if extra else 100
                h = extra.get("height", 50) if extra else 50
                bw = extra.get("border_width", 3) if extra else 3
                color = extra.get("color", "#FFB347") if extra else "#FFB347"
                root.geometry(f"{w}x{h}+{x}+{y}")
                canvas = tk.Canvas(
                    root, width=w, height=h,
                    bg="white", highlightthickness=0,
                )
                canvas.pack()
                canvas.create_rectangle(
                    bw // 2, bw // 2, w - bw // 2, h - bw // 2,
                    outline=color, width=bw,
                )

            elif kind == "scroll":
                # Center on screen
                sw = root.winfo_screenwidth()
                sh = root.winfo_screenheight()
                size = 60
                root.geometry(f"{size}x{size}+{sw // 2 - size // 2}+{sh // 2 - size // 2}")
                canvas = tk.Canvas(
                    root, width=size, height=size,
                    bg="white", highlightthickness=0,
                )
                canvas.pack()
                direction = extra.get("direction", "down") if extra else "down"
                self._draw_scroll_arrow(canvas, size, direction)

            elif kind == "trail":
                sw = root.winfo_screenwidth()
                sh = root.winfo_screenheight()
                root.geometry(f"{sw}x{sh}+0+0")
                canvas = tk.Canvas(
                    root, width=sw, height=sh,
                    bg="white", highlightthickness=0,
                )
                canvas.pack()
                pts = extra.get("points", []) if extra else []
                color = extra.get("color", "#B388FF") if extra else "#B388FF"
                lw = extra.get("line_width", 2) if extra else 2
                self._draw_trail(canvas, pts, color, lw)

            # Auto-destroy after duration
            root.after(duration_ms, root.destroy)
            root.mainloop()

        except Exception:
            # Never let feedback crash the automation
            logger.debug("feedback overlay failed", exc_info=True)
        finally:
            with self._lock:
                self._active_animations = max(0, self._active_animations - 1)

    def _draw_ripple(self, canvas: Any, size: int, cx: int, cy: int) -> None:
        """Draw ripple circles on canvas."""
        color = self._config.ripple_color
        for i in range(3):
            r = self._config.ripple_radius - i * 5
            if r > 0:
                canvas.create_oval(
                    cx - r, cy - r, cx + r, cy + r,
                    outline=color, width=2 - i * 0.5,
                )

    def _draw_scroll_arrow(self, canvas: Any, size: int, direction: str) -> None:
        """Draw a directional arrow for scroll indicator."""
        color = self._config.scroll_color
        mid = size // 2
        margin = 12
        if direction == "up":
            canvas.create_line(mid, size - margin, mid, margin, fill=color, width=3, arrow="last")
        elif direction == "down":
            canvas.create_line(mid, margin, mid, size - margin, fill=color, width=3, arrow="last")
        elif direction == "left":
            canvas.create_line(size - margin, mid, margin, mid, fill=color, width=3, arrow="last")
        elif direction == "right":
            canvas.create_line(margin, mid, size - margin, mid, fill=color, width=3, arrow="last")

    def _draw_trail(
        self,
        canvas: Any,
        points: list[tuple[int, int, float]],
        color: str,
        line_width: int,
    ) -> None:
        """Draw fading trail segments on canvas."""
        if len(points) < 2:
            return
        for i in range(1, len(points)):
            x1, y1, _ = points[i - 1]
            x2, y2, opacity = points[i]
            # Map opacity to stipple pattern for fade effect
            stipple = "" if opacity > 0.6 else "gray50" if opacity > 0.3 else "gray25"
            canvas.create_line(
                x1, y1, x2, y2,
                fill=color, width=line_width, stipple=stipple,
            )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Wait for active animations to finish (best-effort)."""
        deadline = time.monotonic() + 2.0  # 2-second grace period
        while self._active_animations > 0 and time.monotonic() < deadline:
            time.sleep(0.05)
