"""Tests for CLI --visual-feedback flag and SurfaceAdapter feedback hooks — TASK-02 (BATCH-32).

Tests:
  1. --visual-feedback flag is parsed correctly on execute/observe/chat
  2. SurfaceAdapter has set_feedback_engine / get_feedback_engine
  3. WindowsAdapter accepts feedback_engine parameter
  4. WindowsAdapter calls feedback on click when enabled
  5. Feedback is not called when engine is None (HB-01)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deskaoy.cascade.protocol import SurfaceAdapter
from deskaoy.feedback.engine import FeedbackEngine


# ---------------------------------------------------------------------------
# 1. CLI flag parsing
# ---------------------------------------------------------------------------

class TestVisualFeedbackCLI:
    """--visual-feedback flag should be opt-in on execute/observe/chat."""

    def test_execute_flag_default_false(self) -> None:
        """HB-01: --visual-feedback defaults to False."""
        from deskaoy.cli.main import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["execute", "test instruction"])
        assert getattr(args, "visual_feedback", False) is False

    def test_execute_flag_enabled(self) -> None:
        """--visual-feedback sets flag to True."""
        from deskaoy.cli.main import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["execute", "--visual-feedback", "test instruction"])
        assert args.visual_feedback is True

    def test_observe_flag_exists(self) -> None:
        """observe command accepts --visual-feedback."""
        from deskaoy.cli.main import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["observe", "--visual-feedback"])
        assert args.visual_feedback is True

    def test_chat_flag_exists(self) -> None:
        """chat command accepts --visual-feedback."""
        from deskaoy.cli.main import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["chat", "--visual-feedback"])
        assert args.visual_feedback is True


# ---------------------------------------------------------------------------
# 2. SurfaceAdapter feedback hooks
# ---------------------------------------------------------------------------

class TestSurfaceAdapterFeedbackHooks:
    """SurfaceAdapter should support set/get feedback engine."""

    def test_set_and_get_feedback_engine(self) -> None:
        """set_feedback_engine / get_feedback_engine round-trip."""
        adapter = _StubAdapter()
        assert adapter.get_feedback_engine() is None

        engine = FeedbackEngine()
        adapter.set_feedback_engine(engine)
        assert adapter.get_feedback_engine() is engine

    def test_set_feedback_engine_none_disables(self) -> None:
        """Setting engine to None should disable feedback."""
        adapter = _StubAdapter()
        engine = FeedbackEngine()
        adapter.set_feedback_engine(engine)
        adapter.set_feedback_engine(None)
        assert adapter.get_feedback_engine() is None


# ---------------------------------------------------------------------------
# 3. WindowsAdapter feedback integration
# ---------------------------------------------------------------------------

class TestWindowsAdapterFeedback:
    """WindowsAdapter should call feedback hooks on click."""

    def test_feedback_engine_parameter_accepted(self) -> None:
        """WindowsAdapter.__init__ accepts feedback_engine parameter."""
        from deskaoy.adapters.windows import WindowsAdapter

        engine = FeedbackEngine()
        adapter = WindowsAdapter(feedback_engine=engine)
        assert adapter._feedback is engine

    def test_feedback_defaults_to_none(self) -> None:
        """HB-01: feedback_engine defaults to None (opt-in)."""
        from deskaoy.adapters.windows import WindowsAdapter

        adapter = WindowsAdapter()
        assert adapter._feedback is None

    @pytest.mark.asyncio
    async def test_click_calls_feedback_when_enabled(self) -> None:
        """When feedback engine is set and enabled, click triggers feedback hooks."""
        from deskaoy.adapters.windows import WindowsAdapter

        engine = FeedbackEngine()
        engine.enabled = True
        engine._tk_available = True

        adapter = WindowsAdapter(hwnd=12345, feedback_engine=engine)
        adapter._ensure_imports = MagicMock()

        # Make _resolve_hwnd return a fixed value to pass window checks
        adapter._resolve_hwnd = MagicMock(return_value=12345)
        adapter._ensure_window_ready = MagicMock()
        adapter._bring_to_front = MagicMock()
        adapter._check_abort = MagicMock()
        adapter._validate_point_in_window = MagicMock(
            return_value=MagicMock(x=100, y=200)
        )
        adapter._humanized_move = AsyncMock(
            return_value=MagicMock(x=100, y=200)
        )

        mock_pyautogui = MagicMock()
        adapter._pyautogui = mock_pyautogui

        with patch.object(adapter, '_resolve_target', return_value=MagicMock(x=100, y=200)):
            with patch.object(adapter, '_try_uia_pattern_click', return_value=None):
                with patch.object(engine, 'on_before_click') as mock_before:
                    with patch.object(engine, 'on_after_click') as mock_after:
                        # Need to handle asyncio.sleep for settle delay
                        with patch('asyncio.sleep', new_callable=AsyncMock):
                            result = await adapter.click("name:Test")

                            mock_before.assert_called_once_with(100, 200)
                            mock_after.assert_called_once_with(100, 200)

    @pytest.mark.asyncio
    async def test_click_no_feedback_when_none(self) -> None:
        """HB-01: When feedback engine is None, no feedback is called."""
        from deskaoy.adapters.windows import WindowsAdapter

        adapter = WindowsAdapter(hwnd=12345)  # No feedback engine
        adapter._ensure_imports = MagicMock()
        adapter._resolve_hwnd = MagicMock(return_value=12345)
        adapter._ensure_window_ready = MagicMock()
        adapter._bring_to_front = MagicMock()
        adapter._check_abort = MagicMock()
        adapter._validate_point_in_window = MagicMock(
            return_value=MagicMock(x=100, y=200)
        )
        adapter._humanized_move = AsyncMock(
            return_value=MagicMock(x=100, y=200)
        )

        mock_pyautogui = MagicMock()
        adapter._pyautogui = mock_pyautogui

        with patch.object(adapter, '_resolve_target', return_value=MagicMock(x=100, y=200)):
            with patch.object(adapter, '_try_uia_pattern_click', return_value=None):
                with patch('asyncio.sleep', new_callable=AsyncMock):
                    result = await adapter.click("name:Test")
                    assert result.ok is True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _StubAdapter(SurfaceAdapter):
    """Minimal concrete SurfaceAdapter for testing hooks."""

    async def click(self, target: str, *, dry_run: bool = False, **kwargs):
        from deskaoy.results.types import ActionResult
        return ActionResult(ok=True)

    async def fill(self, target: str, value: str, *, dry_run: bool = False, **kwargs):
        from deskaoy.results.types import ActionResult
        return ActionResult(ok=True)

    async def screenshot(self) -> bytes:
        return b""

    async def snapshot(self):
        return MagicMock()

    async def evaluate(self, expression: str):
        return None

    async def key_press(self, key: str, modifiers: int = 0, *, dry_run: bool = False):
        from deskaoy.results.types import ActionResult
        return ActionResult(ok=True)

    async def scroll(self, direction: str, amount: int = 500, *, dry_run: bool = False):
        from deskaoy.results.types import ActionResult
        return ActionResult(ok=True)

    async def type_text(self, text: str, delay_ms: float = 0, *, dry_run: bool = False):
        from deskaoy.results.types import ActionResult
        return ActionResult(ok=True)

    def current_url(self) -> str:
        return ""

    async def current_title(self) -> str:
        return ""
