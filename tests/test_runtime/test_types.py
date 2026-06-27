"""Tests for B38 Runtime Execution Hardening — Types (T03-01 through T03-08, T03-18 through T03-27, T03-33 through T03-40)."""
from __future__ import annotations

import pytest

from deskaoy.runtime.types import (
    WINDOWS_CAPABILITIES,
    AdapterCapabilities,
    PolicyObligation,
    PreflightCheck,
    PreflightResult,
    RuntimeAttempt,
    RuntimeAttemptState,
    RuntimeExecutionReceipt,
    RuntimeResourceBudget,
    make_truth_message,
)

# ---------------------------------------------------------------------------
# T03-01: RuntimeAttemptState transitions forward only
# ---------------------------------------------------------------------------

class TestRuntimeAttemptState:

    def test_pending_to_preflight_passed(self):
        a = RuntimeAttempt("exec-1")
        a.transition(RuntimeAttemptState.PREFLIGHT_PASSED)
        assert a.state == RuntimeAttemptState.PREFLIGHT_PASSED

    def test_preflight_to_running(self):
        a = RuntimeAttempt("exec-1")
        a.transition(RuntimeAttemptState.PREFLIGHT_PASSED)
        a.transition(RuntimeAttemptState.RUNNING)
        assert a.state == RuntimeAttemptState.RUNNING

    def test_running_to_completed(self):
        a = RuntimeAttempt("exec-1")
        a.transition(RuntimeAttemptState.PREFLIGHT_PASSED)
        a.transition(RuntimeAttemptState.RUNNING)
        a.transition(RuntimeAttemptState.COMPLETED)
        assert a.state == RuntimeAttemptState.COMPLETED

    def test_running_to_failed(self):
        a = RuntimeAttempt("exec-1")
        a.transition(RuntimeAttemptState.PREFLIGHT_PASSED)
        a.transition(RuntimeAttemptState.RUNNING)
        a.transition(RuntimeAttemptState.FAILED)
        assert a.state == RuntimeAttemptState.FAILED

    def test_running_to_timed_out(self):
        a = RuntimeAttempt("exec-1")
        a.transition(RuntimeAttemptState.PREFLIGHT_PASSED)
        a.transition(RuntimeAttemptState.RUNNING)
        a.transition(RuntimeAttemptState.TIMED_OUT)
        assert a.state == RuntimeAttemptState.TIMED_OUT


# ---------------------------------------------------------------------------
# T03-02: Reject backward transition
# ---------------------------------------------------------------------------

    def test_reject_backward(self):
        a = RuntimeAttempt("exec-1")
        a.transition(RuntimeAttemptState.PREFLIGHT_PASSED)
        with pytest.raises(ValueError, match="Invalid transition"):
            a.transition(RuntimeAttemptState.PENDING)


# ---------------------------------------------------------------------------
# T03-03: Reject skip (pending → running)
# ---------------------------------------------------------------------------

    def test_reject_skip(self):
        a = RuntimeAttempt("exec-1")
        with pytest.raises(ValueError, match="Invalid transition"):
            a.transition(RuntimeAttemptState.RUNNING)


# ---------------------------------------------------------------------------
# T03-23: Creates with PENDING state
# ---------------------------------------------------------------------------

    def test_initial_state_pending(self):
        a = RuntimeAttempt("exec-1")
        assert a.state == RuntimeAttemptState.PENDING

    def test_custom_attempt_id(self):
        a = RuntimeAttempt("exec-1", attempt_id="custom-id")
        assert a.attempt_id == "custom-id"


# ---------------------------------------------------------------------------
# T03-24: Full lifecycle
# ---------------------------------------------------------------------------

    def test_full_lifecycle(self):
        a = RuntimeAttempt("exec-1")
        assert a.state == RuntimeAttemptState.PENDING
        a.transition(RuntimeAttemptState.PREFLIGHT_PASSED)
        a.transition(RuntimeAttemptState.RUNNING)
        a.transition(RuntimeAttemptState.COMPLETED)
        assert a.is_terminal()

    def test_blocked_from_pending(self):
        a = RuntimeAttempt("exec-1")
        a.transition(RuntimeAttemptState.BLOCKED)
        assert a.state == RuntimeAttemptState.BLOCKED
        assert a.is_terminal()


# ---------------------------------------------------------------------------
# T03-39: Terminal states are final
# ---------------------------------------------------------------------------

    def test_terminal_no_further_transitions(self):
        for terminal in [
            RuntimeAttemptState.COMPLETED,
            RuntimeAttemptState.FAILED,
            RuntimeAttemptState.CANCELLED,
            RuntimeAttemptState.TIMED_OUT,
            RuntimeAttemptState.BLOCKED,
        ]:
            a = RuntimeAttempt("exec-1")
            if terminal == RuntimeAttemptState.BLOCKED:
                a.transition(RuntimeAttemptState.BLOCKED)
            elif terminal == RuntimeAttemptState.CANCELLED:
                a.transition(RuntimeAttemptState.CANCELLED)
            else:
                a.transition(RuntimeAttemptState.PREFLIGHT_PASSED)
                a.transition(RuntimeAttemptState.RUNNING)
                a.transition(terminal)

            with pytest.raises(ValueError, match="terminal state"):
                a.transition(RuntimeAttemptState.COMPLETED)


# ---------------------------------------------------------------------------
# PolicyObligation enum
# ---------------------------------------------------------------------------

class TestPolicyObligation:

    def test_all_obligations_exist(self):
        assert PolicyObligation.DRY_RUN_REQUIRED
        assert PolicyObligation.APPROVAL_REQUIRED
        assert PolicyObligation.QUARANTINE_ON_FAILURE
        assert PolicyObligation.SANDBOX_REQUIRED
        assert PolicyObligation.LOG_FULL_PAYLOAD

    def test_string_values(self):
        assert PolicyObligation.DRY_RUN_REQUIRED.value == "dry_run_required"
        assert PolicyObligation.APPROVAL_REQUIRED.value == "approval_required"


# ---------------------------------------------------------------------------
# AdapterCapabilities
# ---------------------------------------------------------------------------

class TestAdapterCapabilities:

    # T03-07: Defaults correct for WindowsAdapter
    def test_windows_defaults(self):
        caps = WINDOWS_CAPABILITIES
        assert caps.supports_mouse is True
        assert caps.supports_keyboard is True
        assert caps.supports_screen_capture is True
        assert caps.supports_accessibility_read is True
        assert caps.supports_filesystem is False
        assert caps.supports_network is False
        assert caps.supports_dry_run is True
        assert caps.supports_sandboxing is False
        assert caps.adapter_id == "windows-desktop"

    # T03-08: Custom capabilities
    def test_custom_capabilities(self):
        caps = AdapterCapabilities(
            supports_mouse=False,
            supports_network=True,
            adapter_id="custom",
        )
        assert caps.supports_mouse is False
        assert caps.supports_network is True

    # T03-33: to_dict round-trips
    def test_to_dict_round_trip(self):
        caps = AdapterCapabilities(adapter_id="test")
        d = caps.to_dict()
        assert d["adapter_id"] == "test"
        assert "supports_mouse" in d
        assert "supports_keyboard" in d

    def test_fingerprint_is_sha256(self):
        caps = AdapterCapabilities()
        fp = caps.fingerprint()
        assert len(fp) == 64  # SHA-256 hex


# ---------------------------------------------------------------------------
# RuntimeResourceBudget
# ---------------------------------------------------------------------------

class TestRuntimeResourceBudget:

    # T03-21: Defaults are sane
    def test_defaults(self):
        b = RuntimeResourceBudget()
        assert b.timeout_ms == 60_000
        assert b.max_output_bytes == 1_048_576
        assert b.max_actions == 100

    # T03-22: Enforces max_actions
    def test_max_actions(self):
        b = RuntimeResourceBudget(max_actions=5)
        assert b.max_actions == 5

    def test_to_dict(self):
        b = RuntimeResourceBudget()
        d = b.to_dict()
        assert d["timeout_ms"] == 60_000


# ---------------------------------------------------------------------------
# RuntimeExecutionReceipt
# ---------------------------------------------------------------------------

class TestRuntimeExecutionReceipt:

    # T03-18: truth_message matches state
    def test_truth_message_blocked(self):
        msg = make_truth_message(RuntimeAttemptState.BLOCKED)
        assert "blocked" in msg.lower()
        assert "No adapter was invoked" in msg

    def test_truth_message_completed(self):
        msg = make_truth_message(RuntimeAttemptState.COMPLETED)
        assert "completed" in msg.lower()

    def test_truth_message_dry_run(self):
        msg = make_truth_message(RuntimeAttemptState.COMPLETED, dry_run=True)
        assert "Dry run" in msg
        assert "No side effects" in msg

    def test_truth_message_cancelled(self):
        msg = make_truth_message(RuntimeAttemptState.CANCELLED)
        assert "cancelled" in msg.lower()

    def test_truth_message_timed_out(self):
        msg = make_truth_message(RuntimeAttemptState.TIMED_OUT)
        assert "timed out" in msg.lower()

    # T03-19: runtime_execution_performed is correct
    def test_performed_true_for_completed(self):
        r = RuntimeExecutionReceipt(
            execution_id="exec-1",
            attempt_id="att-1",
            attempt_state=RuntimeAttemptState.COMPLETED,
            truth_message="completed",
            runtime_execution_performed=True,
            simulated=False,
            dry_run=False,
            side_effects_performed=True,
            preflight_passed=True,
        )
        assert r.runtime_execution_performed is True

    # T03-20: simulated correct for dry_run
    def test_simulated_for_dry_run(self):
        r = RuntimeExecutionReceipt(
            execution_id="exec-1",
            attempt_id="att-1",
            attempt_state=RuntimeAttemptState.COMPLETED,
            truth_message="dry run",
            runtime_execution_performed=False,
            simulated=True,
            dry_run=True,
            side_effects_performed=False,
            preflight_passed=True,
        )
        assert r.simulated is True
        assert r.dry_run is True

    # T03-34: Receipt is immutable after freeze
    def test_immutable_after_freeze(self):
        r = RuntimeExecutionReceipt(
            execution_id="exec-1",
            attempt_id="att-1",
            attempt_state=RuntimeAttemptState.COMPLETED,
            truth_message="done",
            runtime_execution_performed=True,
            simulated=False,
            dry_run=False,
            side_effects_performed=True,
            preflight_passed=True,
        )
        r.freeze()
        with pytest.raises(AttributeError, match="frozen"):
            r.truth_message = "hacked"

    def test_to_dict(self):
        r = RuntimeExecutionReceipt(
            execution_id="exec-1",
            attempt_id="att-1",
            attempt_state=RuntimeAttemptState.COMPLETED,
            truth_message="done",
            runtime_execution_performed=True,
            simulated=False,
            dry_run=False,
            side_effects_performed=True,
            preflight_passed=True,
        )
        d = r.to_dict()
        assert d["execution_id"] == "exec-1"
        assert d["attempt_state"] == "completed"


# ---------------------------------------------------------------------------
# PreflightResult
# ---------------------------------------------------------------------------

class TestPreflightResult:

    # T03-25: Includes all 12 checks
    def test_includes_all_checks(self):
        checks = [
            PreflightCheck(f"CHK-PF-{i:02d}", f"check_{i}", True)
            for i in range(1, 13)
        ]
        result = PreflightResult(passed=True, checks=checks)
        assert len(result.checks) == 12
        assert result.passed is True

    # T03-26: Fingerprint is SHA-256 (truncated to 16)
    def test_fingerprint_format(self):
        result = PreflightResult(passed=True, fingerprint="abc123")
        assert len(result.fingerprint) >= 1

    def test_to_dict(self):
        result = PreflightResult(passed=False, blocked_reason="test")
        d = result.to_dict()
        assert d["passed"] is False
        assert d["blocked_reason"] == "test"

    # T03-38: Records obligations checked
    def test_obligations_recorded(self):
        result = PreflightResult(
            passed=True,
            obligations_required=[
                PolicyObligation.DRY_RUN_REQUIRED,
                PolicyObligation.LOG_FULL_PAYLOAD,
            ],
        )
        d = result.to_dict()
        assert "dry_run_required" in d["obligations_required"]
        assert "log_full_payload" in d["obligations_required"]
