"""Tests for FeedbackEngine — TASK-01 (BATCH-32).

All tkinter interactions are mocked because:
  1. tkinter.Tk() may fail in headless CI
  2. We test logic, not rendering pixels
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

from deskaoy.feedback.engine import (
    Bounds,
    FeedbackConfig,
    FeedbackEngine,
    ScrollDirection,
    TrailPoint,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(enabled: bool = False) -> FeedbackEngine:
    """Create a FeedbackEngine with tkinter mocked out."""
    engine = FeedbackEngine()
    engine.enabled = enabled
    return engine


def _make_enabled_engine() -> FeedbackEngine:
    """Create a FeedbackEngine with feedback enabled and tkinter available."""
    engine = FeedbackEngine()
    engine.enabled = True
    engine._tk_available = True  # Pretend tkinter is available
    return engine


# ---------------------------------------------------------------------------
# 1. Default state — HB-01 (opt-in only)
# ---------------------------------------------------------------------------

class TestFeedbackEngineDefaultState:
    """FeedbackEngine must be disabled by default."""

    def test_disabled_by_default(self) -> None:
        engine = FeedbackEngine()
        assert engine.enabled is False

    def test_all_methods_are_noop_when_disabled(self) -> None:
        engine = _make_engine(enabled=False)
        assert engine.show_click_ripple(100, 200) is False
        assert engine.show_highlight(Bounds(10, 20, 100, 50)) is False
        assert engine.show_scroll_indicator(ScrollDirection.DOWN) is False
        assert engine.show_cursor_trail([TrailPoint(1, 2)]) is False

    def test_enable_disable_toggle(self) -> None:
        engine = FeedbackEngine()
        engine.enabled = True
        assert engine.enabled is True
        engine.enabled = False
        assert engine.enabled is False


# ---------------------------------------------------------------------------
# 2. show_click_ripple
# ---------------------------------------------------------------------------

class TestClickRipple:
    """Click ripple animation should start when enabled."""

    @patch("deskaoy.feedback.engine.FeedbackEngine._run_overlay")
    def test_ripple_starts_animation(self, mock_overlay: MagicMock) -> None:
        engine = _make_enabled_engine()
        # Prevent actual thread; just check the method returns True
        with patch.object(threading, "Thread", return_value=MagicMock(start=MagicMock())):
            result = engine.show_click_ripple(500, 300)
        assert result is True

    def test_ripple_returns_false_when_disabled(self) -> None:
        engine = _make_engine(enabled=False)
        assert engine.show_click_ripple(500, 300) is False


# ---------------------------------------------------------------------------
# 3. show_highlight
# ---------------------------------------------------------------------------

class TestHighlight:
    """Highlight overlay should start when enabled."""

    @patch("deskaoy.feedback.engine.FeedbackEngine._run_overlay")
    def test_highlight_starts_animation(self, mock_overlay: MagicMock) -> None:
        engine = _make_enabled_engine()
        with patch.object(threading, "Thread", return_value=MagicMock(start=MagicMock())):
            result = engine.show_highlight(Bounds(100, 200, 300, 80))
        assert result is True

    def test_highlight_returns_false_when_disabled(self) -> None:
        engine = _make_engine(enabled=False)
        assert engine.show_highlight(Bounds(0, 0, 100, 100)) is False


# ---------------------------------------------------------------------------
# 4. show_scroll_indicator
# ---------------------------------------------------------------------------

class TestScrollIndicator:
    """Scroll indicator should start for all directions."""

    @patch("deskaoy.feedback.engine.FeedbackEngine._run_overlay")
    def test_scroll_indicator_up(self, mock_overlay: MagicMock) -> None:
        engine = _make_enabled_engine()
        with patch.object(threading, "Thread", return_value=MagicMock(start=MagicMock())):
            result = engine.show_scroll_indicator(ScrollDirection.UP)
        assert result is True

    @patch("deskaoy.feedback.engine.FeedbackEngine._run_overlay")
    def test_scroll_indicator_down(self, mock_overlay: MagicMock) -> None:
        engine = _make_enabled_engine()
        with patch.object(threading, "Thread", return_value=MagicMock(start=MagicMock())):
            result = engine.show_scroll_indicator(ScrollDirection.DOWN)
        assert result is True

    def test_scroll_returns_false_when_disabled(self) -> None:
        engine = _make_engine(enabled=False)
        assert engine.show_scroll_indicator(ScrollDirection.LEFT) is False


# ---------------------------------------------------------------------------
# 5. show_cursor_trail
# ---------------------------------------------------------------------------

class TestCursorTrail:
    """Cursor trail should handle point lists correctly."""

    @patch("deskaoy.feedback.engine.FeedbackEngine._run_overlay")
    def test_trail_starts_with_points(self, mock_overlay: MagicMock) -> None:
        engine = _make_enabled_engine()
        points = [TrailPoint(10, 20), TrailPoint(30, 40), TrailPoint(50, 60)]
        with patch.object(threading, "Thread", return_value=MagicMock(start=MagicMock())):
            result = engine.show_cursor_trail(points)
        assert result is True

    def test_trail_returns_false_for_empty_points(self) -> None:
        engine = _make_enabled_engine()
        assert engine.show_cursor_trail([]) is False

    def test_trail_clamps_to_max_points(self) -> None:
        """Trail should be clamped to trail_max_points."""
        engine = _make_enabled_engine()
        config = FeedbackConfig(trail_max_points=5)
        engine._config = config
        engine.enabled = True

        # Create 10 points — should be clamped to 5
        points = [TrailPoint(i, i) for i in range(10)]
        with patch("deskaoy.feedback.engine.FeedbackEngine._start_animation") as mock_start:
            engine.show_cursor_trail(points)
            # Check that _start_animation was called
            mock_start.assert_called_once()
            call_args = mock_start.call_args
            extra = call_args[1]["extra"]
            # Should have clamped to last 5 points
            assert len(extra["points"]) == 5


# ---------------------------------------------------------------------------
# 6. Active animation tracking
# ---------------------------------------------------------------------------

class TestActiveAnimations:
    """FeedbackEngine should track active animations."""

    def test_active_animations_starts_at_zero(self) -> None:
        engine = FeedbackEngine()
        assert engine.active_animations == 0

    @patch("deskaoy.feedback.engine.FeedbackEngine._run_overlay")
    def test_animation_count_increments(self, mock_overlay: MagicMock) -> None:
        engine = _make_enabled_engine()
        with patch.object(threading, "Thread", return_value=MagicMock(start=MagicMock())):
            engine.show_click_ripple(100, 100)
        # _active_animations is incremented in _start_animation
        assert engine.active_animations == 1


# ---------------------------------------------------------------------------
# 7. Config
# ---------------------------------------------------------------------------

class TestFeedbackConfig:
    """FeedbackConfig defaults should match blueprint."""

    def test_default_config_values(self) -> None:
        config = FeedbackConfig()
        assert config.enabled is False
        assert config.ripple_radius == 20
        assert config.ripple_duration_ms == 400
        assert config.highlight_duration_ms == 500
        assert config.scroll_duration_ms == 300
        assert config.trail_duration_ms == 500
        assert config.trail_max_points == 50

    def test_custom_config(self) -> None:
        config = FeedbackConfig(
            enabled=True,
            ripple_radius=30,
            ripple_duration_ms=600,
        )
        assert config.enabled is True
        assert config.ripple_radius == 30
        assert config.ripple_duration_ms == 600


# ---------------------------------------------------------------------------
# 8. on_before_click / on_after_click hooks
# ---------------------------------------------------------------------------

class TestFeedbackHooks:
    """on_before_click and on_after_click should delegate to show methods."""

    @patch.object(FeedbackEngine, "show_click_ripple")
    def test_on_before_click_calls_ripple(self, mock_ripple: MagicMock) -> None:
        engine = FeedbackEngine()
        engine.on_before_click(100, 200)
        mock_ripple.assert_called_once_with(100, 200)

    def test_on_after_click_is_noop(self) -> None:
        engine = FeedbackEngine()
        # Should not raise
        engine.on_after_click(100, 200)


# ---------------------------------------------------------------------------
# 9. Shutdown
# ---------------------------------------------------------------------------

class TestShutdown:
    """shutdown() should complete without error."""

    def test_shutdown_no_active_animations(self) -> None:
        engine = FeedbackEngine()
        engine.shutdown()  # Should return immediately

    def test_shutdown_with_active_animation(self) -> None:
        engine = FeedbackEngine()
        engine._active_animations = 1
        # Simulate animation completing after short delay
        def _clear():
            time.sleep(0.05)
            with engine._lock:
                engine._active_animations = 0
        t = threading.Thread(target=_clear, daemon=True)
        t.start()
        engine.shutdown()  # Should wait and return


# ---------------------------------------------------------------------------
# 10. tkinter unavailable fallback
# ---------------------------------------------------------------------------

class TestTkinterUnavailable:
    """When tkinter is unavailable, all methods should be no-ops."""

    def test_no_tkinter_show_click_ripple(self) -> None:
        engine = FeedbackEngine()
        engine.enabled = True
        engine._tk_available = False
        assert engine.show_click_ripple(100, 100) is False

    def test_no_tkinter_show_highlight(self) -> None:
        engine = FeedbackEngine()
        engine.enabled = True
        engine._tk_available = False
        assert engine.show_highlight(Bounds(0, 0, 100, 100)) is False

    def test_no_tkinter_show_scroll(self) -> None:
        engine = FeedbackEngine()
        engine.enabled = True
        engine._tk_available = False
        assert engine.show_scroll_indicator(ScrollDirection.DOWN) is False

    def test_no_tkinter_show_trail(self) -> None:
        engine = FeedbackEngine()
        engine.enabled = True
        engine._tk_available = False
        assert engine.show_cursor_trail([TrailPoint(1, 2)]) is False
