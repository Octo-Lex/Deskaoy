"""Click position randomization — avoid perfect center-click patterns.

Why: Anti-bot systems detect clicks that always land on the exact geometric
center of buttons. Real humans click with slight offsets — sometimes left of
center, sometimes right, sometimes slightly above.

This module adds controlled randomness:
  - Gaussian distribution (default): most clicks near center, outliers rare
  - Uniform distribution: even spread within the button area
  - Offset bounded by max_pixels so we never miss the target
"""

from __future__ import annotations

import random

from deskaoy.input.types import HumanizationConfig, Point, Rect


def randomize_click_point(
    target: Point,
    config: HumanizationConfig,
    *,
    bounds: Rect | None = None,
) -> Point:
    """Add jitter to a click target position.

    Args:
        target: The calculated click position (e.g., center of element).
        config: Humanization settings controlling offset magnitude.
        bounds: Optional bounding box of the target element.
                If provided, the offset is clamped to stay within bounds.

    Returns:
        New Point with randomized offset applied.
    """
    max_offset = config.effective_click_offset_max

    if config.click_offset_distribution == "gaussian":
        # Gaussian: 68% of clicks within ±max_offset, 95% within ±2*max_offset
        dx = random.gauss(0, max_offset * 0.5)
        dy = random.gauss(0, max_offset * 0.5)
    else:
        # Uniform: even spread within [-max_offset, +max_offset]
        dx = random.uniform(-max_offset, max_offset)
        dy = random.uniform(-max_offset, max_offset)

    new_x = target.x + dx
    new_y = target.y + dy

    # Clamp to bounds if provided (never click outside the element)
    if bounds is not None:
        margin = 2.0  # stay at least 2px inside the edge
        new_x = max(bounds.x + margin, min(new_x, bounds.x2 - margin))
        new_y = max(bounds.y + margin, min(new_y, bounds.y2 - margin))

    return Point(new_x, new_y)


def randomize_rect_center(
    rect: Rect,
    config: HumanizationConfig,
) -> Point:
    """Get a randomized click point within a bounding rectangle.

    Starts from the rect center, applies jitter, clamps to bounds.

    Args:
        rect: Bounding rectangle of the target element.
        config: Humanization settings.

    Returns:
        Randomized Point within the rectangle.
    """
    center = rect.center
    return randomize_click_point(center, config, bounds=rect)


def random_delay_ms(
    base_ms: float,
    variance_ms: float,
) -> float:
    """Generate a random delay for typing or inter-action timing.

    Args:
        base_ms: Base delay in milliseconds.
        variance_ms: +/- random variance in milliseconds.

    Returns:
        Randomized delay, guaranteed non-negative.
    """
    return max(0, random.gauss(base_ms, variance_ms))
