"""Tests for SessionBudget — session-level resource tracking with escalation."""

from __future__ import annotations

import time

import pytest

from deskaoy.safety.session_budget import (
    EscalationEvent,
    SessionBudget,
    SessionBudgetTracker,
    SessionLimits,
)


# ---------------------------------------------------------------------------
# SessionBudget dataclass
# ---------------------------------------------------------------------------

class TestSessionBudget:
    def test_defaults(self) -> None:
        b = SessionBudget(session_id="s1")
        assert b.actions_evaluated == 0
        assert b.cost_usd == 0.0
        assert b.total_duration_ms == 0.0
        assert b.retries == 0

    def test_elapsed_ms_grows(self) -> None:
        b = SessionBudget(session_id="s1")
        b.started_at = time.monotonic() - 1.0  # 1 second ago
        elapsed = b.elapsed_ms()
        assert elapsed >= 900  # Allow small timing slack


# ---------------------------------------------------------------------------
# SessionLimits
# ---------------------------------------------------------------------------

class TestSessionLimits:
    def test_defaults(self) -> None:
        lim = SessionLimits()
        assert lim.max_actions == 100
        assert lim.max_denials == 10
        assert lim.max_cost_usd == 1.0
        assert lim.max_duration_ms == 1_800_000
        assert lim.escalation_after_actions == 50


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

class TestRecording:
    def test_record_allowed_action(self) -> None:
        tracker = SessionBudgetTracker()
        budget = SessionBudget(session_id="s1")
        tracker.record_action(budget, allowed=True, duration_ms=100.0)
        assert budget.actions_evaluated == 1
        assert budget.actions_allowed == 1
        assert budget.actions_denied == 0
        assert budget.total_duration_ms == 100.0

    def test_record_denied_action(self) -> None:
        tracker = SessionBudgetTracker()
        budget = SessionBudget(session_id="s1")
        tracker.record_action(budget, allowed=False, duration_ms=50.0)
        assert budget.actions_evaluated == 1
        assert budget.actions_allowed == 0
        assert budget.actions_denied == 1

    def test_record_gated_action(self) -> None:
        tracker = SessionBudgetTracker()
        budget = SessionBudget(session_id="s1")
        tracker.record_action(budget, allowed=False, gated=True, duration_ms=30.0)
        assert budget.actions_gated == 1
        assert budget.actions_allowed == 0
        assert budget.actions_denied == 0

    def test_record_with_cost(self) -> None:
        tracker = SessionBudgetTracker()
        budget = SessionBudget(session_id="s1")
        tracker.record_action(budget, allowed=True, duration_ms=100.0, cost_usd=0.05)
        assert budget.cost_usd == 0.05

    def test_record_accumulates(self) -> None:
        tracker = SessionBudgetTracker()
        budget = SessionBudget(session_id="s1")
        tracker.record_action(budget, allowed=True, duration_ms=100.0, cost_usd=0.01)
        tracker.record_action(budget, allowed=False, duration_ms=50.0)
        tracker.record_action(budget, allowed=True, duration_ms=200.0, cost_usd=0.02)
        assert budget.actions_evaluated == 3
        assert budget.actions_allowed == 2
        assert budget.actions_denied == 1
        assert budget.total_duration_ms == 350.0
        assert budget.cost_usd == pytest.approx(0.03)

    def test_record_retry(self) -> None:
        tracker = SessionBudgetTracker()
        budget = SessionBudget(session_id="s1")
        tracker.record_retry(budget)
        tracker.record_retry(budget)
        assert budget.retries == 2


# ---------------------------------------------------------------------------
# should_terminate
# ---------------------------------------------------------------------------

class TestShouldTerminate:
    def test_no_termination_under_limits(self) -> None:
        tracker = SessionBudgetTracker(SessionLimits(max_actions=100))
        budget = SessionBudget(session_id="s1")
        budget.actions_evaluated = 50
        stop, reason = tracker.should_terminate(budget)
        assert stop is False
        assert reason == ""

    def test_terminate_on_max_actions(self) -> None:
        tracker = SessionBudgetTracker(SessionLimits(max_actions=10))
        budget = SessionBudget(session_id="s1")
        budget.actions_evaluated = 10
        stop, reason = tracker.should_terminate(budget)
        assert stop is True
        assert "action limit" in reason

    def test_terminate_on_max_denials(self) -> None:
        tracker = SessionBudgetTracker(SessionLimits(max_denials=3))
        budget = SessionBudget(session_id="s1")
        budget.actions_denied = 3
        stop, reason = tracker.should_terminate(budget)
        assert stop is True
        assert "denial limit" in reason

    def test_terminate_on_max_cost(self) -> None:
        tracker = SessionBudgetTracker(SessionLimits(max_cost_usd=0.5))
        budget = SessionBudget(session_id="s1")
        budget.cost_usd = 0.6
        stop, reason = tracker.should_terminate(budget)
        assert stop is True
        assert "cost limit" in reason

    def test_terminate_on_max_duration(self) -> None:
        tracker = SessionBudgetTracker(SessionLimits(max_duration_ms=1000))
        budget = SessionBudget(session_id="s1")
        budget.started_at = time.monotonic() - 2.0  # 2 seconds ago
        stop, reason = tracker.should_terminate(budget)
        assert stop is True
        assert "duration limit" in reason

    def test_at_exact_limit(self) -> None:
        tracker = SessionBudgetTracker(SessionLimits(max_actions=10))
        budget = SessionBudget(session_id="s1")
        budget.actions_evaluated = 9
        stop, _ = tracker.should_terminate(budget)
        assert stop is False
        budget.actions_evaluated = 10
        stop, _ = tracker.should_terminate(budget)
        assert stop is True


# ---------------------------------------------------------------------------
# should_escalate
# ---------------------------------------------------------------------------

class TestShouldEscalate:
    def test_escalate_at_threshold(self) -> None:
        tracker = SessionBudgetTracker(SessionLimits(escalation_after_actions=5))
        budget = SessionBudget(session_id="s1")
        budget.actions_evaluated = 5
        assert tracker.should_escalate(budget) is True

    def test_no_escalate_below_threshold(self) -> None:
        tracker = SessionBudgetTracker(SessionLimits(escalation_after_actions=5))
        budget = SessionBudget(session_id="s1")
        budget.actions_evaluated = 4
        assert tracker.should_escalate(budget) is False

    def test_escalate_fires_only_once(self) -> None:
        tracker = SessionBudgetTracker(SessionLimits(escalation_after_actions=5))
        budget = SessionBudget(session_id="s1")
        budget.actions_evaluated = 5
        assert tracker.should_escalate(budget) is True
        # Now _escalation_fired is set
        assert tracker.should_escalate(budget) is False
        assert tracker.should_escalate(budget) is False


# ---------------------------------------------------------------------------
# check (returns EscalationEvents)
# ---------------------------------------------------------------------------

class TestCheck:
    def test_no_events_under_limits(self) -> None:
        tracker = SessionBudgetTracker(SessionLimits(max_actions=100, max_denials=10))
        budget = SessionBudget(session_id="s1")
        budget.actions_evaluated = 5
        events = tracker.check(budget)
        assert len(events) == 0

    def test_max_actions_event(self) -> None:
        tracker = SessionBudgetTracker(SessionLimits(max_actions=10))
        budget = SessionBudget(session_id="s1")
        budget.actions_evaluated = 10
        events = tracker.check(budget)
        assert any(e.threshold == "max_actions" for e in events)

    def test_max_denials_event(self) -> None:
        tracker = SessionBudgetTracker(SessionLimits(max_denials=3))
        budget = SessionBudget(session_id="s1")
        budget.actions_denied = 3
        events = tracker.check(budget)
        assert any(e.threshold == "max_denials" for e in events)

    def test_escalation_event(self) -> None:
        tracker = SessionBudgetTracker(SessionLimits(escalation_after_actions=5))
        budget = SessionBudget(session_id="s1")
        budget.actions_evaluated = 5
        events = tracker.check(budget)
        assert any(e.threshold == "escalation" for e in events)

    def test_escalation_event_only_once(self) -> None:
        tracker = SessionBudgetTracker(SessionLimits(escalation_after_actions=5))
        budget = SessionBudget(session_id="s1")
        budget.actions_evaluated = 5
        events1 = tracker.check(budget)
        events2 = tracker.check(budget)
        assert any(e.threshold == "escalation" for e in events1)
        assert not any(e.threshold == "escalation" for e in events2)

    def test_multiple_events_at_once(self) -> None:
        tracker = SessionBudgetTracker(SessionLimits(
            max_actions=10, max_denials=3, escalation_after_actions=5,
        ))
        budget = SessionBudget(session_id="s1")
        budget.actions_evaluated = 10
        budget.actions_denied = 3
        events = tracker.check(budget)
        thresholds = {e.threshold for e in events}
        assert "max_actions" in thresholds
        assert "max_denials" in thresholds
        assert "escalation" in thresholds

    def test_event_fields(self) -> None:
        tracker = SessionBudgetTracker(SessionLimits(max_actions=10))
        budget = SessionBudget(session_id="s1")
        budget.actions_evaluated = 10
        events = tracker.check(budget)
        e = events[0]
        assert e.session_id == "s1"
        assert e.current_value == 10
        assert e.limit_value == 10
        assert e.timestamp > 0


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_fields(self) -> None:
        tracker = SessionBudgetTracker()
        budget = SessionBudget(session_id="s1")
        tracker.record_action(budget, allowed=True, duration_ms=100.0, cost_usd=0.05)
        tracker.record_action(budget, allowed=False, duration_ms=50.0)

        snap = tracker.snapshot(budget)
        assert snap["session_id"] == "s1"
        assert snap["actions_evaluated"] == 2
        assert snap["actions_allowed"] == 1
        assert snap["actions_denied"] == 1
        assert snap["cost_usd"] == pytest.approx(0.05)
        assert snap["total_duration_ms"] == 150.0
        assert snap["retries"] == 0
        assert "elapsed_ms" in snap
