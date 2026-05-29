"""Bezier curve mouse movement — human-like paths with acceleration and jitter.

Why Bezier curves?
  - Anti-bot systems detect instant mouse teleportation (pyautogui.click moves instantly)
  - Real humans move in curves, not straight lines
  - Real humans accelerate at the start and decelerate near the target
  - No two movements are identical

The math:
  - Cubic Bezier: B(t) = (1-t)³P₀ + 3(1-t)²tP₁ + 3(1-t)t²P₂ + t³P₃
  - Control points are randomized around the straight-line path
  - Speed varies via non-uniform t parameterization (ease-in-out)
  - Micro-jitter added per step for realism
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable

from deskaoy.input.types import HumanizationConfig, Point


def _bezier_cubic(t: float, p0: float, p1: float, p2: float, p3: float) -> float:
    """Evaluate cubic Bezier at parameter t ∈ [0, 1]."""
    u = 1 - t
    return u * u * u * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t * t * t * p3


def _ease_in_out(t: float) -> float:
    """Smooth acceleration/deceleration curve.

    Maps uniform t ∈ [0, 1] to non-uniform s ∈ [0, 1]:
      - Slow start (acceleration)
      - Fast middle
      - Slow end (deceleration)

    Uses smoothstep: 3t² - 2t³
    """
    return t * t * (3 - 2 * t)


def _duration_for_distance(distance: float, config: HumanizationConfig) -> float:
    """Calculate move duration based on distance.

    Short moves (e.g. clicking an adjacent button) are fast.
    Long moves (e.g. moving across the screen) are slower.
    Linear interpolation between min and max duration.
    """
    # Zero distance = no movement, use minimum duration exactly
    if distance <= 0:
        return config.move_min_duration_ms

    reference_distance = 800.0  # pixels at which max_duration applies
    ratio = min(distance / reference_distance, 1.0)
    base = config.move_min_duration_ms + ratio * (config.move_max_duration_ms - config.move_min_duration_ms)
    # Add variance
    variance = base * config.move_speed_variance
    result = base + random.uniform(-variance, variance)
    return max(config.move_min_duration_ms, min(result, config.move_max_duration_ms))


def _generate_control_points(
    start: Point,
    end: Point,
    n_points: int,
) -> list[Point]:
    """Generate random control points for a Bezier curve.

    Points are scattered around the straight line from start to end,
    biased toward the perpendicular direction for natural curves.
    """
    dx = end.x - start.x
    dy = end.y - start.y
    distance = math.hypot(dx, dy)

    if distance < 1:
        return [start, end]

    # Perpendicular unit vector
    perp_x = -dy / distance
    perp_y = dx / distance

    # Spread is proportional to distance (bigger moves = wider curves)
    # Clamped to 25% of distance to prevent S-curves or backtracking
    max_spread = distance * 0.25
    sigma = max_spread * 0.4  # ~95% of offsets within max_spread

    points = [start]
    for i in range(1, n_points + 1):
        t = i / (n_points + 1)
        # Base position along the straight line
        base_x = start.x + dx * t
        base_y = start.y + dy * t
        # Perpendicular offset (clamped to max_spread)
        offset = max(-max_spread, min(max_spread, random.gauss(0, sigma)))
        points.append(Point(base_x + perp_x * offset, base_y + perp_y * offset))

    points.append(end)

    # Validate: no control point should deviate >120° from the target direction
    # If a point is "behind" the start, remove it
    target_angle = math.atan2(dy, dx)
    filtered = [points[0]]
    for p in points[1:-1]:
        pdx = p.x - start.x
        pdy = p.y - start.y
        if math.hypot(pdx, pdy) < 1:
            filtered.append(p)
            continue
        angle = math.atan2(pdy, pdx)
        diff = abs(angle - target_angle)
        if diff > math.pi:
            diff = 2 * math.pi - diff
        if diff < math.radians(120):
            filtered.append(p)
        # else: skip this point (too far off-course)
    filtered.append(points[-1])
    return filtered


def compute_bezier_path(
    start: Point,
    end: Point,
    config: HumanizationConfig,
    *,
    num_steps: int | None = None,
) -> list[Point]:
    """Compute the full Bezier curve path from start to end."""
    if config.seed is not None:
        random.seed(config.seed)
    distance = math.hypot(end.x - start.x, end.y - start.y)

    if distance < 2:
        # Negligible movement — just go there
        return [start, end]

    # Generate control points for cubic Bezier segments
    control = _generate_control_points(start, end, config.move_control_points)

    # Calculate steps from duration (aim for ~60Hz mouse move rate)
    duration_ms = _duration_for_distance(distance, config)
    duration_ms = config.move_min_duration_ms + (duration_ms - config.move_min_duration_ms)  # use base for determinism
    steps = num_steps or max(int(duration_ms / 16), 5)  # ~60 steps/sec

    path: list[Point] = []
    n_segments = len(control) - 1

    for step in range(steps + 1):
        # Uniform parameter
        t_raw = step / steps
        # Apply ease-in-out for acceleration/deceleration
        t = _ease_in_out(t_raw)

        # For multiple control points, use piecewise cubic segments
        if n_segments <= 1:
            # Linear interpolation
            x = start.x + (end.x - start.x) * t
            y = start.y + (end.y - start.y) * t
        elif n_segments == 3:
            # Single cubic Bezier
            x = _bezier_cubic(t, control[0].x, control[1].x, control[2].x, control[3].x)
            y = _bezier_cubic(t, control[0].y, control[1].y, control[2].y, control[3].y)
        else:
            # Fallback: linear interpolation across all control points
            segment_t = t * n_segments
            seg_idx = min(int(segment_t), n_segments - 1)
            local_t = segment_t - seg_idx
            p0 = control[seg_idx]
            p1 = control[min(seg_idx + 1, len(control) - 1)]
            x = p0.x + (p1.x - p0.x) * local_t
            y = p0.y + (p1.y - p0.y) * local_t

        # Add micro-jitter (tiny random offset per step)
        if config.effective_micro_jitter > 0 and step not in (0, steps):
            jitter_x = random.gauss(0, config.effective_micro_jitter)
            jitter_y = random.gauss(0, config.effective_micro_jitter)
            x += jitter_x
            y += jitter_y

        path.append(Point(x, y))

    # Ensure we land exactly on target (last point = end)
    if path and (abs(path[-1].x - end.x) > 0.5 or abs(path[-1].y - end.y) > 0.5):
        path[-1] = end

    return path


async def move_mouse(
    start: Point,
    end: Point,
    move_fn: Callable[[Point], None],
    config: HumanizationConfig,
) -> Point:
    """Execute a human-like mouse movement.

    Computes a Bezier path and calls move_fn for each point along the curve
    with appropriate delays to match the target duration.

    Args:
        start: Current mouse position.
        end: Target position.
        move_fn: Platform-specific function that moves the cursor to a Point.
                 Called once per step. May be sync or async.
        config: Humanization settings.

    Returns:
        Final mouse position (should be end).
    """
    import asyncio

    distance = math.hypot(end.x - start.x, end.y - start.y)

    if not config.move_enabled or distance < 2:
        # Instant move (disabled or negligible distance)
        move_fn(end)
        return end

    path = compute_bezier_path(start, end, config)
    duration_ms = _duration_for_distance(distance, config)
    step_delay = duration_ms / max(len(path) - 1, 1)

    for point in path:
        move_fn(point)
        await asyncio.sleep(step_delay / 1000.0)

    return path[-1]
