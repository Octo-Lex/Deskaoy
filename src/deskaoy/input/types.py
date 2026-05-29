"""Input types — mouse, keyboard, and humanization config."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MouseButton(StrEnum):
    LEFT = "left"
    MIDDLE = "middle"
    RIGHT = "right"


class KeyModifier(StrEnum):
    ALT = "alt"
    CTRL = "ctrl"
    SHIFT = "shift"
    META = "meta"  # Cmd on macOS, Win on Windows


@dataclass(frozen=True)
class Point:
    """Screen coordinate."""
    x: float
    y: float

    def __iter__(self):
        yield self.x
        yield self.y


@dataclass(frozen=True)
class Rect:
    """Screen rectangle (x, y = top-left, width, height)."""
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2, self.y + self.height / 2)

    @property
    def x2(self) -> float:
        return self.x + self.width

    @property
    def y2(self) -> float:
        return self.y + self.height

    def contains(self, p: Point) -> bool:
        return self.x <= p.x <= self.x2 and self.y <= p.y <= self.y2


@dataclass
class HumanizationConfig:
    """Controls how human-like the input appears.

    Anti-bot systems detect:
      - Instant mouse teleportation (zero-duration moves)
      - Perfect center-click patterns (always exact center of buttons)
      - Constant-speed mouse movement (real humans accelerate/decelerate)
      - Identical repeated actions (same timing, same coordinates)
    """
    # Bezier curve mouse movement
    move_enabled: bool = True
    move_min_duration_ms: float = 100.0    # short moves (< 100px)
    move_max_duration_ms: float = 500.0    # long moves (> 800px)
    move_control_points: int = 3           # number of random control points
    move_micro_jitter: float = 1.5         # pixels of noise per step
    move_speed_variance: float = 0.3       # +/- 30% speed variation per segment

    # Click position randomization
    click_offset_max: float = 4.0          # max pixels from calculated position
    click_offset_distribution: str = "gaussian"  # gaussian or uniform

    # Typing humanization
    type_base_delay_ms: float = 50.0       # base delay between keystrokes
    type_delay_variance_ms: float = 30.0   # +/- random variance
    type_burst_probability: float = 0.1    # 10% chance of fast burst (no delay)
    type_burst_length: int = 3             # characters in a burst

    # General
    seed: int | None = None             # None = truly random; int = reproducible
    dpi_scale: float = 1.0                 # 1.0 = 100%, 1.5 = 150%, 2.0 = 200% DPI

    @property
    def effective_click_offset_max(self) -> float:
        """Click offset scaled by DPI."""
        return self.click_offset_max * self.dpi_scale

    @property
    def effective_micro_jitter(self) -> float:
        """Micro-jitter scaled by DPI."""
        return self.move_micro_jitter * self.dpi_scale


# ---------------------------------------------------------------------------
# pyautogui '<' bug workaround (OSWorld pattern)
# ---------------------------------------------------------------------------

# Known pyautogui bug: pressing '<' produces '>' instead.
# OSWorld's fix: convert '<' to hotkey("shift", ",") and
# split typewrite strings on '<' characters.


def fix_pyautogui_less_than(text: str) -> str:
    """Fix the pyautogui '<' bug by replacing '<' with a safe alternative.

    pyautogui's ``typewrite`` and ``press`` misinterpret ``'<'`` as ``'>'``.
    This function replaces ``'<'`` with ``','`` (the unshifted key) and
    returns the modified text. The caller should then send ``shift+comma``
    separately before/after the fixed text.

    For a ``press('<')`` command, the caller should use
    ``hotkey('shift', ',')`` instead.

    Args:
        text: Input string that may contain ``'<'`` characters.

    Returns:
        The text with ``'<'`` characters replaced.
    """
    return text.replace('<', ',')
