"""Tests for Compensation Plans engine."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from deskaoy.safety.compensation import (
    CompensatingAction,
    CompensationEngine,
    CompensationPlan,
    RollbackReport,
    RollbackStepResult,
    _compute_inverse,
    _READ_ONLY_ACTIONS,
    _IRREVERSIBLE_ACTIONS,
)
from deskaoy.results.types import ActionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _surface_ok() -> AsyncMock:
    """Create a mock surface that returns ok=True for all methods."""
    surface = AsyncMock()
    surface.fill.return_value = ActionResult(ok=True, data={})
    surface.scroll.return_value = ActionResult(ok=True, data={})
    surface.navigate.return_value = ActionResult(ok=True, data={})
    return surface


def _ledger_mock() -> AsyncMock:
    """Create a mock evidence ledger."""
    ledger = AsyncMock()
    ledger.append = AsyncMock()
    return ledger


# ---------------------------------------------------------------------------
# _compute_inverse tests
# ---------------------------------------------------------------------------


class TestComputeInverse:
    """Tests for the _compute_inverse function."""

    def test_fill_stores_previous_value(self):
        comp = _compute_inverse("fill", "email", {"value": "old@test.com"}, {"value": "new@test.com"})
        assert comp.action == "fill"
        assert comp.strategy == "restore_state"
        assert comp.can_rollback is True
        assert comp.inverse_action == "fill"
        assert comp.inverse_params == {"target": "email", "value": "old@test.com"}

    def test_fill_missing_before_value(self):
        comp = _compute_inverse("fill", "input1", {}, {"value": "x"})
        assert comp.can_rollback is True
        assert comp.inverse_params["value"] == ""

    def test_fill_uses_text_fallback(self):
        comp = _compute_inverse("fill", "el", {"text": "hello"}, {})
        assert comp.inverse_params["value"] == "hello"

    def test_type_text_stores_previous_text(self):
        comp = _compute_inverse("type_text", "field", {"value": "abc"}, {"text": "abcdef"})
        assert comp.strategy == "restore_state"
        assert comp.can_rollback is True
        assert comp.inverse_action == "fill"
        assert comp.inverse_params["value"] == "abc"

    def test_type_text_uses_focus_from_before_state(self):
        comp = _compute_inverse("type_text", "field", {"text": "old", "focus": "target_el"}, {})
        assert comp.inverse_params["target"] == "target_el"

    def test_type_text_falls_back_to_target(self):
        comp = _compute_inverse("type_text", "default_el", {"text": "old"}, {})
        assert comp.inverse_params["target"] == "default_el"

    def test_scroll_down_reverses_to_up(self):
        comp = _compute_inverse("scroll", "", {}, {"direction": "down", "amount": 300})
        assert comp.strategy == "restore_state"
        assert comp.can_rollback is True
        assert comp.inverse_action == "scroll"
        assert comp.inverse_params == {"direction": "up", "amount": 300}

    def test_scroll_up_reverses_to_down(self):
        comp = _compute_inverse("scroll", "", {}, {"direction": "up", "amount": 500})
        assert comp.inverse_params["direction"] == "down"

    def test_scroll_left_reverses_to_right(self):
        comp = _compute_inverse("scroll", "", {}, {"direction": "left", "amount": 200})
        assert comp.inverse_params["direction"] == "right"

    def test_scroll_right_reverses_to_left(self):
        comp = _compute_inverse("scroll", "", {}, {"direction": "right"})
        assert comp.inverse_params["direction"] == "left"

    def test_scroll_defaults_to_up(self):
        comp = _compute_inverse("scroll", "", {}, {"amount": 100})
        assert comp.inverse_params["direction"] == "up"

    def test_navigate_stores_previous_url(self):
        comp = _compute_inverse("navigate", "", {"url": "https://old.com"}, {"url": "https://new.com"})
        assert comp.strategy == "restore_state"
        assert comp.can_rollback is True
        assert comp.inverse_action == "navigate"
        assert comp.inverse_params["url"] == "https://old.com"

    def test_navigate_uses_current_url_fallback(self):
        comp = _compute_inverse("navigate", "", {"current_url": "https://fallback.com"}, {})
        assert comp.inverse_params["url"] == "https://fallback.com"

    def test_navigate_no_previous_url(self):
        comp = _compute_inverse("navigate", "", {}, {"url": "https://new.com"})
        assert comp.can_rollback is False
        assert comp.inverse_params["url"] == ""

    def test_click_is_irreversible(self):
        comp = _compute_inverse("click", "btn", {}, {})
        assert comp.strategy == "none"
        assert comp.can_rollback is False
        assert comp.inverse_action == "none"

    def test_key_press_is_irreversible(self):
        comp = _compute_inverse("key_press", "Enter", {}, {})
        assert comp.strategy == "none"
        assert comp.can_rollback is False

    def test_screenshot_is_readonly(self):
        comp = _compute_inverse("screenshot", "", {}, {})
        assert comp.strategy == "none"
        assert comp.can_rollback is True  # read-only = no rollback needed

    def test_snapshot_is_readonly(self):
        comp = _compute_inverse("snapshot", "", {}, {})
        assert comp.strategy == "none"
        assert comp.can_rollback is True

    def test_evaluate_is_readonly(self):
        comp = _compute_inverse("evaluate", "", {}, {})
        assert comp.strategy == "none"
        assert comp.can_rollback is True

    def test_unknown_action_is_irreversible(self):
        comp = _compute_inverse("custom_action", "x", {}, {})
        assert comp.strategy == "none"
        assert comp.can_rollback is False

    def test_priority_fill_higher_than_scroll(self):
        fill = _compute_inverse("fill", "x", {"value": "a"}, {})
        scroll = _compute_inverse("scroll", "", {}, {"direction": "down"})
        assert fill.priority > scroll.priority

    def test_priority_navigate_highest(self):
        nav = _compute_inverse("navigate", "", {"url": "https://a.com"}, {})
        fill = _compute_inverse("fill", "x", {"value": "a"}, {})
        assert nav.priority > fill.priority


# ---------------------------------------------------------------------------
# CompensationEngine.register tests
# ---------------------------------------------------------------------------


class TestRegister:
    """Tests for CompensationEngine.register()."""

    def test_register_fill(self):
        engine = CompensationEngine()
        comp = engine.register("exec1", "fill", "email", {"value": "old"}, {"value": "new"})
        assert comp.action == "fill"
        assert comp.execution_id == "exec1"
        assert comp.can_rollback is True

    def test_register_click(self):
        engine = CompensationEngine()
        comp = engine.register("exec1", "click", "btn", {}, {})
        assert comp.can_rollback is False

    def test_register_stores_in_registry(self):
        engine = CompensationEngine()
        engine.register("exec1", "fill", "a", {"value": "x"}, {})
        engine.register("exec1", "click", "b", {}, {})
        assert engine.get_registered_count("exec1") == 2

    def test_register_separate_executions(self):
        engine = CompensationEngine()
        engine.register("exec1", "fill", "a", {"value": "x"}, {})
        engine.register("exec2", "fill", "b", {"value": "y"}, {})
        assert engine.get_registered_count("exec1") == 1
        assert engine.get_registered_count("exec2") == 1

    def test_register_default_params(self):
        engine = CompensationEngine()
        comp = engine.register("e1", "fill", "t", {"value": "v"})
        assert comp.action == "fill"


# ---------------------------------------------------------------------------
# CompensationEngine.build_plan tests
# ---------------------------------------------------------------------------


class TestBuildPlan:
    """Tests for CompensationEngine.build_plan()."""

    def test_empty_registry(self):
        engine = CompensationEngine()
        plan = engine.build_plan("nonexistent")
        assert len(plan.steps) == 0
        assert plan.execution_id == "nonexistent"
        assert plan.plan_id  # non-empty

    def test_steps_in_reverse_order(self):
        engine = CompensationEngine()
        engine.register("e1", "fill", "a", {"value": "1"}, {})
        engine.register("e1", "fill", "b", {"value": "2"}, {})
        engine.register("e1", "fill", "c", {"value": "3"}, {})
        plan = engine.build_plan("e1")
        # LIFO: c, b, a
        assert plan.steps[0].target == "c"
        assert plan.steps[1].target == "b"
        assert plan.steps[2].target == "a"

    def test_plan_has_created_at(self):
        engine = CompensationEngine()
        plan = engine.build_plan("e1")
        assert plan.created_at  # non-empty ISO string

    def test_readonly_actions_included_in_plan(self):
        engine = CompensationEngine()
        engine.register("e1", "screenshot", "", {}, {})
        plan = engine.build_plan("e1")
        assert len(plan.steps) == 1
        assert plan.steps[0].can_rollback is True  # but strategy=none


# ---------------------------------------------------------------------------
# CompensationEngine.execute_plan tests
# ---------------------------------------------------------------------------


class TestExecutePlan:
    """Tests for CompensationEngine.execute_plan()."""

    @pytest.mark.asyncio
    async def test_execute_fill_rollback(self):
        surface = _surface_ok()
        engine = CompensationEngine(surface=surface)
        engine.register("e1", "fill", "email", {"value": "old@test.com"}, {"value": "new@test.com"})

        plan = engine.build_plan("e1")
        report = await engine.execute_plan(plan)

        assert report.succeeded == 1
        assert report.failed == 0
        assert report.skipped == 0
        surface.fill.assert_called_once_with("email", "old@test.com")

    @pytest.mark.asyncio
    async def test_execute_scroll_rollback(self):
        surface = _surface_ok()
        engine = CompensationEngine(surface=surface)
        engine.register("e1", "scroll", "", {}, {"direction": "down", "amount": 300})

        plan = engine.build_plan("e1")
        report = await engine.execute_plan(plan)

        assert report.succeeded == 1
        surface.scroll.assert_called_once_with("up", 300)

    @pytest.mark.asyncio
    async def test_execute_navigate_rollback(self):
        surface = _surface_ok()
        engine = CompensationEngine(surface=surface)
        engine.register("e1", "navigate", "", {"url": "https://old.com"}, {})

        plan = engine.build_plan("e1")
        report = await engine.execute_plan(plan)

        assert report.succeeded == 1
        surface.navigate.assert_called_once_with("https://old.com")

    @pytest.mark.asyncio
    async def test_skip_readonly_actions(self):
        surface = _surface_ok()
        engine = CompensationEngine(surface=surface)
        engine.register("e1", "screenshot", "", {}, {})
        engine.register("e1", "snapshot", "", {}, {})

        plan = engine.build_plan("e1")
        report = await engine.execute_plan(plan)

        assert report.succeeded == 0
        assert report.skipped == 2
        assert report.failed == 0

    @pytest.mark.asyncio
    async def test_skip_irreversible_actions(self):
        surface = _surface_ok()
        engine = CompensationEngine(surface=surface)
        engine.register("e1", "click", "btn", {}, {})
        engine.register("e1", "key_press", "Enter", {}, {})

        plan = engine.build_plan("e1")
        report = await engine.execute_plan(plan)

        assert report.skipped == 2
        assert report.succeeded == 0

    @pytest.mark.asyncio
    async def test_continues_on_individual_failure(self):
        surface = _surface_ok()
        # First fill fails, second succeeds
        surface.fill.side_effect = [
            ActionResult(ok=False, data={"error": "fail"}),
            ActionResult(ok=True, data={}),
        ]
        engine = CompensationEngine(surface=surface)
        engine.register("e1", "fill", "a", {"value": "1"}, {})
        engine.register("e1", "fill", "b", {"value": "2"}, {})

        plan = engine.build_plan("e1")
        report = await engine.execute_plan(plan)

        # LIFO: b first (ok), then a (fail)
        assert report.succeeded == 1
        assert report.failed == 1

    @pytest.mark.asyncio
    async def test_no_surface_returns_all_failed(self):
        engine = CompensationEngine(surface=None)
        engine.register("e1", "fill", "a", {"value": "1"}, {})

        plan = engine.build_plan("e1")
        report = await engine.execute_plan(plan)

        assert report.succeeded == 0
        assert report.failed == 1
        assert "No surface adapter" in report.results[0].description

    @pytest.mark.asyncio
    async def test_records_to_ledger(self):
        surface = _surface_ok()
        ledger = _ledger_mock()
        engine = CompensationEngine(surface=surface, ledger=ledger)
        engine.register("e1", "fill", "a", {"value": "old"}, {})

        plan = engine.build_plan("e1")
        report = await engine.execute_plan(plan)

        assert ledger.append.called
        call_args = ledger.append.call_args
        assert call_args[0][1] == "action:rollback"

    @pytest.mark.asyncio
    async def test_ledger_failure_does_not_crash(self):
        surface = _surface_ok()
        ledger = _ledger_mock()
        ledger.append.side_effect = RuntimeError("disk full")
        engine = CompensationEngine(surface=surface, ledger=ledger)
        engine.register("e1", "fill", "a", {"value": "old"}, {})

        plan = engine.build_plan("e1")
        report = await engine.execute_plan(plan)

        # Should succeed despite ledger failure
        assert report.succeeded == 1

    @pytest.mark.asyncio
    async def test_surface_exception_handled(self):
        surface = _surface_ok()
        surface.fill.side_effect = RuntimeError("window closed")
        engine = CompensationEngine(surface=surface)
        engine.register("e1", "fill", "a", {"value": "old"}, {})

        plan = engine.build_plan("e1")
        report = await engine.execute_plan(plan)

        assert report.failed == 1
        assert "exception" in report.results[0].description.lower()

    @pytest.mark.asyncio
    async def test_navigate_no_url_skipped(self):
        surface = _surface_ok()
        engine = CompensationEngine(surface=surface)
        engine.register("e1", "navigate", "", {}, {})  # no previous URL → can_rollback=False

        plan = engine.build_plan("e1")
        report = await engine.execute_plan(plan)

        # can_rollback=False means it gets skipped, not executed
        assert report.skipped == 1
        assert "not reversible" in report.results[0].description

    @pytest.mark.asyncio
    async def test_report_counts_correct(self):
        surface = _surface_ok()
        engine = CompensationEngine(surface=surface)
        engine.register("e1", "fill", "a", {"value": "1"}, {})     # reversible
        engine.register("e1", "click", "btn", {}, {})              # irreversible
        engine.register("e1", "screenshot", "", {}, {})            # read-only

        plan = engine.build_plan("e1")
        report = await engine.execute_plan(plan)

        assert report.total_steps == 3
        assert report.succeeded == 1
        assert report.skipped == 2  # click + screenshot

    @pytest.mark.asyncio
    async def test_lifo_order_with_three_fills(self):
        surface = _surface_ok()
        engine = CompensationEngine(surface=surface)
        engine.register("e1", "fill", "a", {"value": "1"}, {})
        engine.register("e1", "fill", "b", {"value": "2"}, {})
        engine.register("e1", "fill", "c", {"value": "3"}, {})

        plan = engine.build_plan("e1")
        report = await engine.execute_plan(plan)

        assert report.succeeded == 3
        # Verify LIFO: c, b, a
        calls = surface.fill.call_args_list
        assert calls[0][0] == ("c", "3")
        assert calls[1][0] == ("b", "2")
        assert calls[2][0] == ("a", "1")


# ---------------------------------------------------------------------------
# Cleanup tests
# ---------------------------------------------------------------------------


class TestCleanup:
    """Tests for clear() and clear_all()."""

    def test_clear_removes_execution(self):
        engine = CompensationEngine()
        engine.register("e1", "fill", "a", {"value": "x"}, {})
        engine.register("e2", "fill", "b", {"value": "y"}, {})

        engine.clear("e1")
        assert engine.get_registered_count("e1") == 0
        assert engine.get_registered_count("e2") == 1

    def test_clear_nonexistent_is_noop(self):
        engine = CompensationEngine()
        engine.clear("nonexistent")  # no crash

    def test_clear_all(self):
        engine = CompensationEngine()
        engine.register("e1", "fill", "a", {}, {})
        engine.register("e2", "fill", "b", {})

        engine.clear_all()
        assert engine.get_registered_count("e1") == 0
        assert engine.get_registered_count("e2") == 0


# ---------------------------------------------------------------------------
# Surface setter tests
# ---------------------------------------------------------------------------


class TestSurfaceSetter:
    """Tests for surface property setter."""

    @pytest.mark.asyncio
    async def test_surface_can_be_set_later(self):
        engine = CompensationEngine(surface=None)
        engine.register("e1", "fill", "a", {"value": "old"}, {})

        # Before setting surface — would fail
        plan = engine.build_plan("e1")
        report = await engine.execute_plan(plan)
        assert report.failed == 1

        # Set surface and retry
        surface = _surface_ok()
        engine.surface = surface
        engine.register("e2", "fill", "a", {"value": "old"}, {})
        plan2 = engine.build_plan("e2")
        report2 = await engine.execute_plan(plan2)
        assert report2.succeeded == 1
