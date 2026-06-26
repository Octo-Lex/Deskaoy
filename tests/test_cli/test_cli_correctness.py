"""CLI correctness smoke tests — Batch 4.

Covers:
  1. ``execute --capability`` is honored (not hardcoded to ``automate``).
  2. ``schedule due`` uses ``r.prompt`` (not the nonexistent ``r.instruction``).
  3. ``version`` subcommand produces output.
  4. ``execute --dry-run`` with non-automate capability routes correctly.
  5. Storage path delegates to ``StorageResolver``.
"""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest

from deskaoy.cli.main import _build_goal, _resolve_storage_dir

# ---------------------------------------------------------------------------
# 1. execute --capability is honored
# ---------------------------------------------------------------------------

class TestBuildGoalCapability:

    def _make_args(self, **overrides) -> argparse.Namespace:
        defaults = dict(
            instruction=None,
            capability="automate",
            target=None,
            value=None,
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    # ── automate ──

    def test_automate_uses_instruction_param(self):
        args = self._make_args(capability="automate", instruction="Open Notepad")
        goal = _build_goal(args)
        assert goal.capability == "automate"
        assert goal.params == {"instruction": "Open Notepad"}

    def test_automate_without_instruction_errors(self):
        args = self._make_args(capability="automate", instruction=None)
        with pytest.raises(SystemExit):
            _build_goal(args)

    # ── click ──

    def test_click_uses_target_from_flag(self):
        args = self._make_args(capability="click", target="OK button", instruction="ignored")
        goal = _build_goal(args)
        assert goal.capability == "click"
        assert goal.params["target"] == "OK button"

    def test_click_falls_back_to_instruction_as_target(self):
        """`deskaoy execute --capability click "OK button"` → target="OK button"."""
        args = self._make_args(capability="click", instruction="OK button")
        goal = _build_goal(args)
        assert goal.capability == "click"
        assert goal.params["target"] == "OK button"

    def test_click_without_target_or_instruction_errors(self):
        args = self._make_args(capability="click", target=None, instruction=None)
        with pytest.raises(SystemExit):
            _build_goal(args)

    # ── fill ──

    def test_fill_with_target_and_value(self):
        args = self._make_args(capability="fill", target="name field", value="John")
        goal = _build_goal(args)
        assert goal.capability == "fill"
        assert goal.params == {"target": "name field", "value": "John"}

    def test_fill_without_value_errors(self):
        args = self._make_args(capability="fill", target="name field", value=None)
        with pytest.raises(SystemExit):
            _build_goal(args)

    # ── type_text ──

    def test_type_text_maps_value_to_text(self):
        args = self._make_args(capability="type_text", value="hello world")
        goal = _build_goal(args)
        assert goal.capability == "type_text"
        assert goal.params == {"text": "hello world"}

    def test_type_text_falls_back_to_instruction_as_text(self):
        args = self._make_args(capability="type_text", instruction="hello world")
        goal = _build_goal(args)
        assert goal.params == {"text": "hello world"}

    # ── key_press ──

    def test_key_press_maps_value_to_key(self):
        args = self._make_args(capability="key_press", value="Enter")
        goal = _build_goal(args)
        assert goal.capability == "key_press"
        assert goal.params == {"key": "Enter"}

    # ── scroll ──

    def test_scroll_maps_value_to_direction(self):
        args = self._make_args(capability="scroll", value="down")
        goal = _build_goal(args)
        assert goal.capability == "scroll"
        assert goal.params == {"direction": "down"}

    # ── navigate ──

    def test_navigate_maps_value_to_url(self):
        args = self._make_args(capability="navigate", value="https://example.com")
        goal = _build_goal(args)
        assert goal.capability == "navigate"
        assert goal.params == {"url": "https://example.com"}

    # ── unsupported ──

    def test_unsupported_capability_errors_clearly(self):
        """Capabilities without a CLI param mapping must fail, not produce wrong params."""
        args = self._make_args(capability="orchestrate", instruction="test")
        with pytest.raises(SystemExit):
            _build_goal(args)

    def test_non_automate_capability_not_silently_routed_as_automate(self):
        """The core regression: --capability click must NOT become automate."""
        args = self._make_args(capability="click", target="btn")
        goal = _build_goal(args)
        assert goal.capability != "automate"
        assert goal.capability == "click"


# ---------------------------------------------------------------------------
# 2. schedule due uses r.prompt
# ---------------------------------------------------------------------------

class TestScheduleDue:

    @pytest.mark.asyncio
    async def test_due_prints_prompt_not_instruction(self, capsys):
        """Regression: `schedule due` crashed with AttributeError on r.instruction.

        The Routine dataclass field is `prompt`, not `instruction`.
        """
        from deskaoy.cli.main import _cmd_schedule_due
        from deskaoy.routines import Routine

        # Create a real Routine with the prompt field
        routine = Routine(
            name="test-routine",
            prompt="Open Notepad and type Hello",
            schedule="*/5 * * * *",
            enabled=True,
        )

        agent = MagicMock()
        agent.routine_scheduler = MagicMock()
        agent.routine_scheduler.get_due = MagicMock(return_value=[routine])

        args = argparse.Namespace(storage_dir=None)

        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            result = await _cmd_schedule_due(args)

        assert result == 0
        captured = capsys.readouterr()
        # Must contain the prompt text, not crash
        assert "Open Notepad and type Hello" in captured.out
        assert "test-routine" in captured.out


# ---------------------------------------------------------------------------
# 3. version subcommand
# ---------------------------------------------------------------------------

class TestVersionCommand:

    @pytest.mark.asyncio
    async def test_version_prints_current_version(self, capsys):
        from deskaoy.cli.main import _cmd_version
        args = argparse.Namespace()
        result = await _cmd_version(args)
        assert result == 0
        captured = capsys.readouterr()
        import deskaoy
        assert deskaoy.__version__ in captured.out


# ---------------------------------------------------------------------------
# 4. execute --dry-run routes correctly for non-automate
# ---------------------------------------------------------------------------

class TestExecuteDryRunCapability:

    @pytest.mark.asyncio
    async def test_dry_run_click_routes_as_click(self):
        """execute --dry-run --capability click must build a click goal, not automate."""
        from deskaoy.cli.main import _cmd_execute, _reset_agent

        _reset_agent()

        args = argparse.Namespace(
            instruction="OK button",
            capability="click",
            target=None,
            value=None,
            dry_run=True,
            timeout=60,
            session=None,
            storage_dir=None,
            json=False,
            visual_feedback=False,
            daemon=False,
        )

        captured_goal = {}

        async def fake_execute(goal, ctx):
            captured_goal["capability"] = goal.capability
            captured_goal["params"] = goal.params
            from deskaoy.os_types import AgentResult, Confidence, ResultStatus
            return AgentResult(
                execution_id="test",
                status=ResultStatus.DRY_RUN,
                summary="dry run",
                confidence=Confidence(score=1.0, reason="test"),
            )

        agent = MagicMock()
        agent.execute = fake_execute

        with patch("deskaoy.cli.main._get_agent", return_value=agent):
            await _cmd_execute(args)

        assert captured_goal["capability"] == "click"
        assert captured_goal["params"]["target"] == "OK button"


# ---------------------------------------------------------------------------
# 5. Storage path delegates to StorageResolver
# ---------------------------------------------------------------------------

class TestStoragePathReconciliation:

    def test_resolve_storage_dir_uses_storage_resolver(self):
        """_resolve_storage_dir must delegate to StorageResolver, not hardcode paths."""
        from deskaoy.storage import StorageResolver

        # When no explicit dir given, must match StorageResolver.capability_root
        resolved = _resolve_storage_dir(None)
        expected = str(StorageResolver().capability_root)
        assert resolved == expected

    def test_explicit_storage_dir_wins(self):
        """An explicit storage_dir argument always takes precedence."""
        resolved = _resolve_storage_dir("/tmp/custom-deskaoy")
        assert resolved == "/tmp/custom-deskaoy"
