"""Tests for input module — Bezier curves, jitter, humanization."""


import pytest

from deskaoy.input.bezier import (
    _duration_for_distance,
    _ease_in_out,
    _generate_control_points,
    compute_bezier_path,
    move_mouse,
)
from deskaoy.input.jitter import (
    random_delay_ms,
    randomize_click_point,
    randomize_rect_center,
)
from deskaoy.input.types import HumanizationConfig, Point, Rect

# =============================================================================
# Bezier Curve Tests
# =============================================================================

class TestEaseInOut:
    def test_endpoints(self):
        assert _ease_in_out(0.0) == 0.0
        assert abs(_ease_in_out(1.0) - 1.0) < 1e-10

    def test_midpoint(self):
        mid = _ease_in_out(0.5)
        assert 0.4 < mid < 0.6  # near 0.5

    def test_monotonic(self):
        """Ease curve should be monotonically increasing."""
        prev = 0
        for i in range(1, 100):
            t = i / 100
            val = _ease_in_out(t)
            assert val > prev
            prev = val


class TestDurationForDistance:
    def test_short_move_is_fast(self):
        config = HumanizationConfig(move_min_duration_ms=100, move_max_duration_ms=500)
        dur = _duration_for_distance(10, config)
        assert dur < 200

    def test_long_move_is_slow(self):
        config = HumanizationConfig(move_min_duration_ms=100, move_max_duration_ms=500)
        dur = _duration_for_distance(1000, config)
        assert dur > 300

    def test_zero_distance(self):
        config = HumanizationConfig()
        dur = _duration_for_distance(0, config)
        assert dur <= config.move_min_duration_ms


class TestControlPoints:
    def test_generates_correct_count(self):
        start = Point(0, 0)
        end = Point(500, 500)
        points = _generate_control_points(start, end, 3)
        assert len(points) == 5  # start + 3 control + end

    def test_first_and_last_are_endpoints(self):
        start = Point(10, 20)
        end = Point(300, 400)
        points = _generate_control_points(start, end, 3)
        assert points[0] == start
        assert points[-1] == end

    def test_tiny_distance(self):
        start = Point(0, 0)
        end = Point(0.5, 0.5)
        points = _generate_control_points(start, end, 3)
        assert len(points) == 2  # just start + end


class TestComputeBezierPath:
    def test_start_and_end(self):
        start = Point(0, 0)
        end = Point(200, 200)
        config = HumanizationConfig(move_enabled=True, seed=42)
        path = compute_bezier_path(start, end, config)
        assert path[0] == start
        assert path[-1] == end

    def test_enough_steps(self):
        start = Point(0, 0)
        end = Point(1000, 1000)
        config = HumanizationConfig(move_enabled=True, seed=42)
        path = compute_bezier_path(start, end, config)
        assert len(path) > 5

    def test_negligible_distance(self):
        start = Point(100, 100)
        end = Point(100.5, 100.5)
        config = HumanizationConfig()
        path = compute_bezier_path(start, end, config)
        assert len(path) == 2

    def test_deterministic_with_seed(self):
        start = Point(0, 0)
        end = Point(500, 500)
        config = HumanizationConfig(seed=42)
        path1 = compute_bezier_path(start, end, config)
        config2 = HumanizationConfig(seed=42)
        path2 = compute_bezier_path(start, end, config2)
        assert len(path1) == len(path2)
        for p1, p2 in zip(path1, path2, strict=False):
            assert abs(p1.x - p2.x) < 0.01
            assert abs(p1.y - p2.y) < 0.01

    def test_non_deterministic_without_seed(self):
        start = Point(0, 0)
        end = Point(500, 500)
        config = HumanizationConfig(seed=None)
        paths = [compute_bezier_path(start, end, config) for _ in range(5)]
        # At least one should differ (extremely unlikely all 5 are identical)
        all_same = all(
            paths[0][i].x == paths[j][i].x
            for j in range(1, 5)
            for i in range(min(len(p) for p in paths))
        )
        assert not all_same

    def test_jitter_moves_points_off_curve(self):
        start = Point(0, 0)
        end = Point(500, 500)
        config_no_jitter = HumanizationConfig(move_micro_jitter=0, seed=42)
        config_with_jitter = HumanizationConfig(move_micro_jitter=5.0, seed=42)
        path_clean = compute_bezier_path(start, end, config_no_jitter, num_steps=20)
        path_jitter = compute_bezier_path(start, end, config_with_jitter, num_steps=20)
        # At least some middle points should differ
        diffs = sum(
            1 for p1, p2 in zip(path_clean[1:-1], path_jitter[1:-1], strict=False)
            if abs(p1.x - p2.x) > 0.1 or abs(p1.y - p2.y) > 0.1
        )
        assert diffs > 0


class TestMoveMouse:
    @pytest.mark.asyncio
    async def test_instant_when_disabled(self):
        calls = []
        def move_fn(p):
            return calls.append(p)
        config = HumanizationConfig(move_enabled=False)
        result = await move_mouse(Point(0, 0), Point(100, 100), move_fn, config)
        assert len(calls) == 1
        assert result.x == 100
        assert result.y == 100

    @pytest.mark.asyncio
    async def test_multiple_steps_when_enabled(self):
        calls = []
        def move_fn(p):
            return calls.append(p)
        config = HumanizationConfig(move_enabled=True, move_min_duration_ms=200)
        result = await move_mouse(Point(0, 0), Point(500, 500), move_fn, config)
        assert len(calls) > 2
        assert abs(result.x - 500) < 1
        assert abs(result.y - 500) < 1

    @pytest.mark.asyncio
    async def test_tiny_distance_is_instant(self):
        calls = []
        def move_fn(p):
            return calls.append(p)
        config = HumanizationConfig(move_enabled=True)
        await move_mouse(Point(100, 100), Point(101, 101), move_fn, config)
        assert len(calls) == 1


# =============================================================================
# Jitter / Randomization Tests
# =============================================================================

class TestRandomizeClickPoint:
    def test_gaussian_offset(self):
        config = HumanizationConfig(click_offset_max=4.0, click_offset_distribution="gaussian")
        target = Point(500, 500)
        # Run many times and check distribution
        offsets_x = []
        for _ in range(1000):
            p = randomize_click_point(target, config)
            offsets_x.append(p.x - target.x)
        # Mean should be near 0
        assert abs(sum(offsets_x) / len(offsets_x)) < 1.0
        # Most should be within ±4 pixels
        within_4 = sum(1 for x in offsets_x if abs(x) <= 4)
        assert within_4 > 500  # >50% within 1 std dev

    def test_uniform_offset(self):
        config = HumanizationConfig(click_offset_max=4.0, click_offset_distribution="uniform")
        target = Point(500, 500)
        offsets = [randomize_click_point(target, config).x - target.x for _ in range(1000)]
        # All should be within ±4
        assert all(-4 <= o <= 4 for o in offsets)
        # Spread across range
        assert min(offsets) < -2
        assert max(offsets) > 2

    def test_clamped_to_bounds(self):
        config = HumanizationConfig(click_offset_max=10.0)
        target = Point(50, 50)
        bounds = Rect(x=40, y=40, width=20, height=20)  # 40-60 range
        for _ in range(100):
            p = randomize_click_point(target, config, bounds=bounds)
            assert 42 <= p.x <= 58  # 2px margin
            assert 42 <= p.y <= 58


class TestRandomizeRectCenter:
    def test_stays_in_rect(self):
        config = HumanizationConfig(click_offset_max=5.0)
        rect = Rect(x=100, y=100, width=200, height=100)
        for _ in range(100):
            p = randomize_rect_center(rect, config)
            assert 102 <= p.x <= 298  # 2px margin inside
            assert 102 <= p.y <= 198

    def test_near_center(self):
        config = HumanizationConfig(click_offset_max=3.0)
        rect = Rect(x=0, y=0, width=100, height=100)
        points = [randomize_rect_center(rect, config) for _ in range(100)]
        avg_x = sum(p.x for p in points) / len(points)
        avg_y = sum(p.y for p in points) / len(points)
        # Average should be near center (50, 50)
        assert abs(avg_x - 50) < 3
        assert abs(avg_y - 50) < 3


class TestRandomDelay:
    def test_non_negative(self):
        for _ in range(100):
            delay = random_delay_ms(50, 30)
            assert delay >= 0

    def test_near_base(self):
        delays = [random_delay_ms(100, 10) for _ in range(1000)]
        avg = sum(delays) / len(delays)
        assert 90 < avg < 110  # mean near 100


# =============================================================================
# Types Tests
# =============================================================================

class TestPoint:
    def test_iterable(self):
        p = Point(10, 20)
        x, y = p
        assert x == 10
        assert y == 20


class TestRect:
    def test_center(self):
        r = Rect(x=100, y=200, width=50, height=80)
        assert r.center.x == 125
        assert r.center.y == 240

    def test_contains(self):
        r = Rect(x=0, y=0, width=100, height=100)
        assert r.contains(Point(50, 50))
        assert r.contains(Point(0, 0))
        assert r.contains(Point(100, 100))
        assert not r.contains(Point(150, 50))

    def test_x2_y2(self):
        r = Rect(x=10, y=20, width=30, height=40)
        assert r.x2 == 40
        assert r.y2 == 60
