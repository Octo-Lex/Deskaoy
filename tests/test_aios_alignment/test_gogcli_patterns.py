"""Tests for gogcli-inspired safety & observability patterns.

Covers:
  A — Expanded status codes (RATE_LIMITED, RETRYABLE, EMPTY_RESULTS, CONFIG_ERROR)
  B — Circuit breaker (threshold, cooldown, half-open)
  C — Action guard filtering (enabled_actions / disabled_actions)
  D — Machine-readable capability schema
  E — Retry policy with exponential backoff + jitter
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from deskaoy.os_types import (
    AgentContext,
    AgentGoal,
    AgentResult,
    CancellationToken,
    Confidence,
    ErrorCode,
    IssueSeverity,
    ResultStatus,
)
from deskaoy.policy import PolicyBridge, PolicyEffect
from deskaoy.recovery_bridge import (
    CircuitBreaker,
    RecoveryBridge,
    RecoveryEvent,
    RecoveryEventType,
    RetryPolicy,
)
from deskaoy.results.types import ActionError, ActionResult, ErrorCategory
from deskaoy.trace_bridge import TraceBridge


# =====================================================================
# Fixtures
# =====================================================================

def _make_context(**overrides: Any) -> AgentContext:
    defaults = dict(
        execution_id="test-exec-001",
        idempotency_key="idem-001",
        task_id="task-001",
        user_id="user-001",
        session_id="sess-001",
    )
    defaults.update(overrides)
    return AgentContext(**defaults)


def _make_goal(capability: str = "click", **params: Any) -> AgentGoal:
    return AgentGoal(capability=capability, params=params)


# =====================================================================
# A — Expanded Status Codes
# =====================================================================

class TestExpandedStatusCodes:
    """Status codes from gogcli exit-code pattern."""

    def test_rate_limited_exists(self) -> None:
        assert ResultStatus.RATE_LIMITED == "rate_limited"

    def test_retryable_exists(self) -> None:
        assert ResultStatus.RETRYABLE == "retryable"

    def test_empty_results_exists(self) -> None:
        assert ResultStatus.EMPTY_RESULTS == "empty_results"

    def test_config_error_exists(self) -> None:
        assert ResultStatus.CONFIG_ERROR == "config_error"

    def test_all_old_codes_preserved(self) -> None:
        """Backward compat — no regression on existing status codes."""
        assert ResultStatus.SUCCESS == "success"
        assert ResultStatus.PARTIAL == "partial"
        assert ResultStatus.FAILURE == "failure"
        assert ResultStatus.CANCELLED == "cancelled"
        assert ResultStatus.NEEDS_REVIEW == "needs_review"
        assert ResultStatus.DRY_RUN == "dry_run"

    @pytest.mark.asyncio
    async def test_timeout_returns_failure(self) -> None:
        """asyncio.TimeoutError → FAILURE status with TIMED_OUT receipt (BATCH-03)."""
        from deskaoy.desktop_agent import DesktopAgent

        surface = MagicMock()
        surface.click = AsyncMock(side_effect=asyncio.TimeoutError)
        surface.current_title = AsyncMock(return_value="test")
        surface.current_url = AsyncMock(return_value="about:blank")
        surface.name = "mock"

        agent = DesktopAgent(surface=surface)
        ctx = _make_context(timeout_seconds=1)
        goal = _make_goal("click", target="btn")

        result = await agent.execute(goal, ctx)
        assert result.status == ResultStatus.FAILURE
        assert any(i.code == ErrorCode.TIMEOUT for i in result.issues)
        # BATCH-03: receipt with TIMED_OUT attempt state
        assert result.data.get("receipt", {}).get("attempt_state") == "timed_out"

    @pytest.mark.asyncio
    async def test_connection_error_returns_retryable(self) -> None:
        """ConnectionError → RETRYABLE status."""
        from deskaoy.desktop_agent import DesktopAgent

        surface = MagicMock()
        surface.click = AsyncMock(side_effect=ConnectionError("network down"))
        surface.current_title = AsyncMock(return_value="test")
        surface.current_url = AsyncMock(return_value="about:blank")
        surface.name = "mock"

        agent = DesktopAgent(surface=surface)
        ctx = _make_context()
        goal = _make_goal("click", target="btn")

        result = await agent.execute(goal, ctx)
        assert result.status == ResultStatus.RETRYABLE

    @pytest.mark.asyncio
    async def test_no_surface_returns_config_error(self) -> None:
        """Missing surface adapter → CONFIG_ERROR status."""
        from deskaoy.desktop_agent import DesktopAgent

        agent = DesktopAgent()  # No surface
        ctx = _make_context()
        goal = _make_goal("click", target="btn")

        result = await agent.execute(goal, ctx)
        assert result.status == ResultStatus.CONFIG_ERROR


# =====================================================================
# B — Circuit Breaker
# =====================================================================

class TestCircuitBreaker:
    """gogcli-style circuit breaker: threshold → open → cooldown → half-open."""

    def test_starts_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.state == "closed"
        assert not cb.is_open()

    def test_opens_after_threshold(self) -> None:
        cb = CircuitBreaker(threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"  # Not yet
        just_opened = cb.record_failure()
        assert just_opened is True
        assert cb.state == "open"
        assert cb.is_open()

    def test_success_resets_circuit(self) -> None:
        cb = CircuitBreaker(threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.is_open()
        cb.record_success()
        assert cb.state == "closed"
        assert not cb.is_open()

    def test_cooldown_allows_half_open(self) -> None:
        cb = CircuitBreaker(threshold=2, cooldown=0.05)  # 50ms
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open()
        time.sleep(0.15)  # Wait well past cooldown (generous margin for CI)
        assert not cb.is_open()  # Half-open → allows one probe

    def test_cooldown_not_elapsed_stays_open(self) -> None:
        cb = CircuitBreaker(threshold=2, cooldown=60.0)  # 60s
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open()
        # Still open — cooldown hasn't elapsed

    def test_failure_count_increments(self) -> None:
        cb = CircuitBreaker(threshold=5)
        assert cb.failure_count == 0
        cb.record_failure()
        assert cb.failure_count == 1
        cb.record_failure()
        assert cb.failure_count == 2

    def test_failure_count_resets_on_success(self) -> None:
        cb = CircuitBreaker(threshold=5)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 0

    def test_reset_force_closes(self) -> None:
        cb = CircuitBreaker(threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open()
        cb.reset()
        assert cb.state == "closed"
        assert not cb.is_open()

    def test_wired_into_recovery_bridge_can_retry(self) -> None:
        bridge = RecoveryBridge(max_attempts=5)
        # Trip the circuit breaker
        for _ in range(5):
            bridge.circuit_breaker.record_failure()
        assert bridge.circuit_breaker.is_open()
        assert bridge.can_retry("click") is False

    def test_circuit_breaker_default_params(self) -> None:
        cb = CircuitBreaker()
        assert cb._threshold == 5
        assert cb._cooldown == 30.0


# =====================================================================
# C — Action Guard Filtering
# =====================================================================

class TestActionGuardFiltering:
    """gogcli-style enable/disable commands pattern."""

    def test_no_guards_allows_all(self) -> None:
        policy = PolicyBridge(dev_mode=True)
        assert policy.is_action_allowed("click") is True
        assert policy.is_action_allowed("navigate") is True

    def test_enabled_guard_allows_only_listed(self) -> None:
        policy = PolicyBridge(
            dev_mode=True,
            enabled_actions={"click", "fill", "screenshot"},
        )
        assert policy.is_action_allowed("click") is True
        assert policy.is_action_allowed("fill") is True
        assert policy.is_action_allowed("navigate") is False

    def test_disabled_guard_blocks_listed(self) -> None:
        policy = PolicyBridge(
            dev_mode=True,
            disabled_actions={"navigate"},
        )
        assert policy.is_action_allowed("click") is True
        assert policy.is_action_allowed("navigate") is False

    def test_dot_path_matching_blocks_children(self) -> None:
        """Disabling 'gmail' blocks 'gmail.send' and 'gmail.search'."""
        policy = PolicyBridge(
            dev_mode=True,
            disabled_actions={"gmail"},
        )
        assert policy.is_action_allowed("gmail.send") is False
        assert policy.is_action_allowed("gmail.search") is False
        assert policy.is_action_allowed("calendar.list") is True

    def test_enabled_dot_path_allows_children(self) -> None:
        policy = PolicyBridge(
            dev_mode=True,
            enabled_actions={"click"},
        )
        assert policy.is_action_allowed("click") is True
        assert policy.is_action_allowed("click.double") is True
        assert policy.is_action_allowed("fill") is False

    def test_disabled_overrides_enabled(self) -> None:
        policy = PolicyBridge(
            dev_mode=True,
            enabled_actions={"click", "navigate"},
            disabled_actions={"navigate"},
        )
        assert policy.is_action_allowed("click") is True
        assert policy.is_action_allowed("navigate") is False

    @pytest.mark.asyncio
    async def test_guard_checked_in_preflight(self) -> None:
        """Blocked action → DENY even in dev mode."""
        policy = PolicyBridge(
            dev_mode=True,
            disabled_actions={"navigate"},
        )
        decision = await policy.preflight("navigate")
        assert decision.effect == PolicyEffect.DENY
        assert "blocked by action guard" in decision.reason

    @pytest.mark.asyncio
    async def test_allowed_action_passes_preflight(self) -> None:
        policy = PolicyBridge(
            dev_mode=True,
            enabled_actions={"click", "fill"},
        )
        decision = await policy.preflight("click")
        assert decision.effect == PolicyEffect.ALLOW


# =====================================================================
# D — Machine-Readable Capability Schema
# =====================================================================

class TestCapabilitySchema:
    """gogcli-style schema() JSON output."""

    def test_schema_returns_dict(self) -> None:
        from deskaoy.desktop_agent import DesktopAgent
        agent = DesktopAgent()
        schema = agent.schema()
        assert isinstance(schema, dict)

    def test_schema_version(self) -> None:
        from deskaoy.desktop_agent import DesktopAgent
        schema = DesktopAgent().schema()
        assert schema["schema_version"] == 1

    def test_commands_listed(self) -> None:
        from deskaoy.desktop_agent import DesktopAgent, CAPABILITIES
        schema = DesktopAgent().schema()
        capabilities = schema["capabilities"]
        assert len(capabilities) == len(CAPABILITIES)
        names = set(capabilities.keys())
        assert "click" in names
        assert "automate" in names

    def test_command_metadata(self) -> None:
        from deskaoy.desktop_agent import DesktopAgent
        schema = DesktopAgent().schema()
        click = schema["capabilities"]["click"]
        assert click["description"]
        assert click["action_class"] == "sensitive"
        assert click["impact_level"] == "low"
        assert isinstance(click["permissions"], list)

    def test_permissions_list(self) -> None:
        from deskaoy.desktop_agent import DesktopAgent
        schema = DesktopAgent().schema()
        assert isinstance(schema["permissions_required"], list)
        assert len(schema["permissions_required"]) > 0

    def test_bridges_status(self) -> None:
        from deskaoy.desktop_agent import DesktopAgent
        schema = DesktopAgent().schema()
        assert "bridges" in schema["status"]
        assert "policy" in schema["status"]["bridges"]
        assert "trace" in schema["status"]["bridges"]
        assert isinstance(schema["status"]["bridges"]["policy"], bool)

    def test_circuit_breaker_in_schema(self) -> None:
        from deskaoy.desktop_agent import DesktopAgent
        schema = DesktopAgent().schema()
        assert "circuit_breaker" in schema["status"]
        assert schema["status"]["circuit_breaker"]["state"] in ("open", "closed")


# =====================================================================
# E — Retry Policy with Exponential Backoff + Jitter
# =====================================================================

class TestRetryPolicy:
    """gogcli-style exponential backoff with jitter."""

    def test_delay_increases_exponentially(self) -> None:
        policy = RetryPolicy(base_delay=1.0, jitter_fraction=0.0)
        assert policy.delay_for_attempt(0) == 1.0
        assert policy.delay_for_attempt(1) == 2.0
        assert policy.delay_for_attempt(2) == 4.0

    def test_delay_capped_at_max(self) -> None:
        policy = RetryPolicy(base_delay=1.0, max_delay=5.0, jitter_fraction=0.0)
        assert policy.delay_for_attempt(10) == 5.0  # Would be 1024 without cap

    def test_jitter_adds_randomness(self) -> None:
        policy = RetryPolicy(base_delay=1.0, jitter_fraction=0.5)
        # Run 20 samples — at least some should differ
        delays = {policy.delay_for_attempt(0) for _ in range(20)}
        assert len(delays) > 1  # Jitter means not all identical

    def test_should_retry_retryable_code(self) -> None:
        policy = RetryPolicy()
        assert policy.should_retry("timeout", 0) is True
        assert policy.should_retry("network_error", 0) is True
        assert policy.should_retry("rate_limited", 0) is True

    def test_should_not_retry_non_retryable(self) -> None:
        policy = RetryPolicy()
        assert policy.should_retry("not_found", 0) is False
        assert policy.should_retry("validation_error", 0) is False

    def test_should_not_retry_after_max(self) -> None:
        policy = RetryPolicy(max_retries=3)
        assert policy.should_retry("timeout", 0) is True
        assert policy.should_retry("timeout", 2) is True
        assert policy.should_retry("timeout", 3) is False  # At limit

    def test_default_retryable_codes(self) -> None:
        policy = RetryPolicy()
        assert "timeout" in policy.retryable_codes
        assert "network_error" in policy.retryable_codes
        assert "rate_limited" in policy.retryable_codes

    def test_default_params(self) -> None:
        policy = RetryPolicy()
        assert policy.max_retries == 3
        assert policy.base_delay == 1.0
        assert policy.max_delay == 30.0

    @pytest.mark.asyncio
    async def test_wait_and_retry_records_attempt(self) -> None:
        bridge = RecoveryBridge()
        result = await bridge.wait_and_retry("click", "timeout")
        assert result is True
        assert bridge._attempt_counts.get("click") == 1

    @pytest.mark.asyncio
    async def test_wait_and_retry_rejects_non_retryable(self) -> None:
        bridge = RecoveryBridge()
        result = await bridge.wait_and_retry("click", "not_found")
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_and_retry_blocked_by_circuit(self) -> None:
        bridge = RecoveryBridge()
        # Trip the circuit breaker
        for _ in range(5):
            bridge.circuit_breaker.record_failure()
        result = await bridge.wait_and_retry("click", "timeout")
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_and_retry_respects_max_retries(self) -> None:
        policy = RetryPolicy(max_retries=2)
        bridge = RecoveryBridge(retry_policy=policy)
        # Exhaust retries
        await bridge.wait_and_retry("click", "timeout")  # attempt 1
        await bridge.wait_and_retry("click", "timeout")  # attempt 2
        result = await bridge.wait_and_retry("click", "timeout")  # attempt 3 → blocked
        assert result is False
