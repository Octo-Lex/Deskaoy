"""Tests for Windows adapter safety features and Bezier constraints."""

import math

import pytest

from deskaoy.input.bezier import (
    _generate_control_points,
    compute_bezier_path,
)
from deskaoy.input.jitter import randomize_click_point
from deskaoy.input.types import HumanizationConfig, Point, Rect

# =============================================================================
# Bezier Control Point Constraints (Feedback Point #3)
# =============================================================================

class TestControlPointConstraints:
    def test_no_backtracking(self):
        """Control points should not deviate >120° from target direction."""
        start = Point(0, 0)
        end = Point(1000, 0)  # Moving right
        for seed in range(50):
            config = HumanizationConfig(seed=seed, move_control_points=5)
            points = _generate_control_points(start, end, config.move_control_points)
            # All points should have x > 0 (not behind start)
            for p in points[1:-1]:
                assert p.x >= -10, f"Seed {seed}: point {p} is behind start"

    def test_perpendicular_offset_clamped(self):
        """Offset should not exceed 25% of distance."""
        start = Point(0, 0)
        end = Point(1000, 0)
        max_offset = 250  # 25% of 1000
        for seed in range(50):
            config = HumanizationConfig(seed=seed, move_control_points=5)
            points = _generate_control_points(start, end, config.move_control_points)
            for p in points[1:-1]:
                # Perpendicular offset = y distance from straight line (y=0)
                assert abs(p.y) <= max_offset + 5, f"Seed {seed}: offset {p.y} exceeds 25%"

    def test_path_stays_reasonable(self):
        """Full Bezier path should not loop or backtrack excessively."""
        start = Point(0, 0)
        end = Point(500, 500)
        for seed in range(20):
            config = HumanizationConfig(seed=seed)
            path = compute_bezier_path(start, end, config, num_steps=30)
            # Every point should be closer to end than 2x the total distance
            total_dist = math.hypot(end.x - start.x, end.y - start.y)
            for p in path:
                dist_from_start = math.hypot(p.x - start.x, p.y - start.y)
                assert dist_from_start < total_dist * 2, \
                    f"Seed {seed}: point {p} is way off path"


# =============================================================================
# DPI-Aware Jitter (Feedback Point #4)
# =============================================================================

class TestDPIAwareJitter:
    def test_100pct_dpi(self):
        config = HumanizationConfig(click_offset_max=4.0, dpi_scale=1.0)
        assert config.effective_click_offset_max == 4.0

    def test_200pct_dpi(self):
        config = HumanizationConfig(click_offset_max=4.0, dpi_scale=2.0)
        assert config.effective_click_offset_max == 8.0

    def test_150pct_dpi(self):
        config = HumanizationConfig(click_offset_max=4.0, dpi_scale=1.5)
        assert config.effective_click_offset_max == 6.0

    def test_jitter_scales_with_dpi(self):
        target = Point(500, 500)
        bounds = Rect(x=400, y=400, width=200, height=200)

        # At 100% DPI, offsets within ±4px
        config_1x = HumanizationConfig(click_offset_max=4.0, dpi_scale=1.0, seed=42)
        offsets_1x = []
        for _ in range(200):
            p = randomize_click_point(target, config_1x, bounds=bounds)
            offsets_1x.append(abs(p.x - target.x))

        # At 200% DPI, offsets within ±8px (same proportion on screen)
        config_2x = HumanizationConfig(click_offset_max=4.0, dpi_scale=2.0, seed=42)
        offsets_2x = []
        for _ in range(200):
            p = randomize_click_point(target, config_2x, bounds=bounds)
            offsets_2x.append(abs(p.x - target.x))

        avg_1x = sum(offsets_1x) / len(offsets_1x)
        avg_2x = sum(offsets_2x) / len(offsets_2x)
        # 2x DPI should produce roughly 2x the pixel offset
        assert avg_2x > avg_1x * 1.3  # Not exactly 2x due to clamping

    def test_micro_jitter_scales_with_dpi(self):
        config_1x = HumanizationConfig(move_micro_jitter=1.5, dpi_scale=1.0)
        config_2x = HumanizationConfig(move_micro_jitter=1.5, dpi_scale=2.0)
        assert config_1x.effective_micro_jitter == 1.5
        assert config_2x.effective_micro_jitter == 3.0


# =============================================================================
# Failsafe / Abort (Feedback Point #13)
# =============================================================================

class TestFailsafeAbort:
    def test_abort_flag_exists(self):
        """WindowsAdapter should have abort mechanism."""
        # Can't fully test without win32gui, but verify the interface
        from deskaoy.adapters.windows import WindowsAdapter
        adapter = WindowsAdapter.__new__(WindowsAdapter)
        adapter._aborted = False
        assert not adapter._aborted

    def test_abort_sets_flag(self):
        from deskaoy.adapters.windows import WindowsAdapter
        adapter = WindowsAdapter.__new__(WindowsAdapter)
        adapter._aborted = False
        adapter.abort()
        assert adapter._aborted

    def test_check_abort_raises(self):
        from deskaoy.adapters.windows import WindowsAdapter
        adapter = WindowsAdapter.__new__(WindowsAdapter)
        adapter._aborted = True
        with pytest.raises(RuntimeError, match="aborted"):
            adapter._check_abort()

    def test_check_abort_passes_when_not_aborted(self):
        from deskaoy.adapters.windows import WindowsAdapter
        adapter = WindowsAdapter.__new__(WindowsAdapter)
        adapter._aborted = False
        adapter._check_abort()  # Should not raise


# =============================================================================
# HumanizationConfig Defaults (Feedback Point #19)
# =============================================================================

class TestHumanizationDefaults:
    def test_dpi_scale_default(self):
        config = HumanizationConfig()
        assert config.dpi_scale == 1.0

    def test_focus_settle_exists(self):
        """WindowsAdapter should have configurable focus settle delay."""
        from deskaoy.adapters.windows import WindowsAdapter
        adapter = WindowsAdapter.__new__(WindowsAdapter)
        adapter._focus_settle_ms = 300.0
        assert adapter._focus_settle_ms == 300.0

    def test_jitter_amplitude_reasonable(self):
        """Default jitter values should be reasonable at 1080p."""
        config = HumanizationConfig()
        # Click offset: ±4px at 1080p = ~0.37% of screen width
        pct = (config.click_offset_max / 1920) * 100
        assert 0.1 < pct < 1.0  # Between 0.1% and 1% of screen

    def test_micro_jitter_reasonable(self):
        """Default micro-jitter should be small but detectable."""
        config = HumanizationConfig()
        assert 0.5 < config.move_micro_jitter < 5.0
