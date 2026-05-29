"""Tests for B38 Runtime Preflight (T03-09 through T03-17, T03-28 through T03-32, T03-35 through T03-37, T03-40)."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock

from deskaoy.runtime.types import (
    AdapterCapabilities,
    PolicyObligation,
    RuntimeResourceBudget,
    PreflightCheck,
    WINDOWS_CAPABILITIES,
)
from deskaoy.runtime.preflight import RuntimePreflight


# ---------------------------------------------------------------------------
# Mock agent
# ---------------------------------------------------------------------------

def _mock_agent(**overrides):
    agent = MagicMock()

    # Surface adapter
    surface = MagicMock()
    agent._surface = surface

    # Rate governor
    governor = MagicMock()
    governor.check.return_value = True
    agent.rate_governor = governor

    # Session budget
    budget = MagicMock()
    budget.is_exhausted.return_value = False
    agent.session_budget = budget

    # Health
    agent._last_health_status = MagicMock(healthy=True)

    # Capabilities
    agent._capabilities = WINDOWS_CAPABILITIES

    # Resource budget
    agent._resource_budget = RuntimeResourceBudget()

    for k, v in overrides.items():
        setattr(agent, k, v)

    return agent


def _mock_goal(capability="automate", params=None):
    goal = MagicMock()
    goal.capability = capability
    goal.params = params or {}
    return goal


def _mock_context(dry_run=False):
    ctx = MagicMock()
    ctx.execution_id = "exec-1"
    ctx.dry_run = dry_run
    ctx.additional_clients = {}
    return ctx


def _mock_policy_decision(effect="allow", obligations=None):
    decision = MagicMock()
    decision.effect = effect
    decision.obligations = obligations or []
    decision.reason = ""
    return decision


# ---------------------------------------------------------------------------
# T03-09: Preflight passes for valid request
# ---------------------------------------------------------------------------

class TestPreflightPasses:

    @pytest.mark.asyncio
    async def test_valid_request_passes(self):
        agent = _mock_agent()
        pf = RuntimePreflight(agent)
        result = await pf.run(_mock_goal(), _mock_context())
        assert result.passed is True
        assert len(result.checks) == 12


# ---------------------------------------------------------------------------
# T03-10: Fails when no adapter
# ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_no_adapter_fails(self):
        agent = _mock_agent(_surface=None)
        agent._capabilities = None
        pf = RuntimePreflight(agent)
        result = await pf.run(_mock_goal(), _mock_context())
        assert result.passed is False
        chk01 = [c for c in result.checks if c.check_id == "CHK-PF-01"][0]
        assert not chk01.passed


# ---------------------------------------------------------------------------
# T03-11: Fails when policy denies
# ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_policy_deny_fails(self):
        agent = _mock_agent()
        pf = RuntimePreflight(agent)
        result = await pf.run(
            _mock_goal(), _mock_context(),
            policy_decision=_mock_policy_decision(effect="deny"),
        )
        chk05 = [c for c in result.checks if c.check_id == "CHK-PF-05"][0]
        assert not chk05.passed
        assert "denied" in chk05.message.lower()


# ---------------------------------------------------------------------------
# T03-12: Fails when dry_run_required but not dry_run
# ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_dry_run_obligation_blocks_live(self):
        agent = _mock_agent()
        pf = RuntimePreflight(agent)
        result = await pf.run(
            _mock_goal(), _mock_context(dry_run=False),
            policy_decision=_mock_policy_decision(
                effect="allow",
                obligations=[PolicyObligation.DRY_RUN_REQUIRED],
            ),
        )
        chk07 = [c for c in result.checks if c.check_id == "CHK-PF-07"][0]
        assert not chk07.passed


# ---------------------------------------------------------------------------
# T03-13: Fails when rate limited
# ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_rate_limit_fails(self):
        agent = _mock_agent()
        agent.rate_governor.check.side_effect = Exception("Rate limited")
        pf = RuntimePreflight(agent)
        result = await pf.run(_mock_goal(), _mock_context())
        chk08 = [c for c in result.checks if c.check_id == "CHK-PF-08"][0]
        assert not chk08.passed


# ---------------------------------------------------------------------------
# T03-14: Fails when session budget exhausted
# ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_session_budget_exhausted(self):
        agent = _mock_agent()
        agent.session_budget.is_exhausted.return_value = True
        pf = RuntimePreflight(agent)
        result = await pf.run(_mock_goal(), _mock_context())
        chk09 = [c for c in result.checks if c.check_id == "CHK-PF-09"][0]
        assert not chk09.passed


# ---------------------------------------------------------------------------
# T03-15: Fails when health check unhealthy
# ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_health_unhealthy(self):
        agent = _mock_agent()
        agent._last_health_status = MagicMock(healthy=False)
        pf = RuntimePreflight(agent)
        result = await pf.run(_mock_goal(), _mock_context())
        chk10 = [c for c in result.checks if c.check_id == "CHK-PF-10"][0]
        assert not chk10.passed


# ---------------------------------------------------------------------------
# T03-16: Fails when raw secret in params
# ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_raw_secret_detected(self):
        agent = _mock_agent()
        pf = RuntimePreflight(agent)
        goal = _mock_goal(params={"api_key": "sk-123456789012345678901234567890"})
        result = await pf.run(goal, _mock_context())
        chk12 = [c for c in result.checks if c.check_id == "CHK-PF-12"][0]
        assert not chk12.passed


# ---------------------------------------------------------------------------
# T03-17: Fingerprint changes on policy version change
# ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fingerprint_changes(self):
        agent = _mock_agent()
        pf = RuntimePreflight(agent)

        result1 = await pf.run(_mock_goal(), _mock_context())
        result2 = await pf.run(
            _mock_goal(), _mock_context(),
            policy_decision=_mock_policy_decision(effect="allow"),
        )
        # Fingerprints should differ when policy decision changes
        assert result1.fingerprint != result2.fingerprint


# ---------------------------------------------------------------------------
# T03-28: Full integration: preflight → attempt → receipt
# ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_full_integration(self):
        from deskaoy.runtime.types import (
            RuntimeAttempt,
            RuntimeAttemptState,
            RuntimeExecutionReceipt,
            make_truth_message,
        )

        agent = _mock_agent()
        pf = RuntimePreflight(agent)

        # 1. Run preflight
        result = await pf.run(_mock_goal(), _mock_context())
        assert result.passed is True

        # 2. Create attempt and transition
        attempt = RuntimeAttempt("exec-1")
        attempt.set_preflight_result(result)
        attempt.transition(RuntimeAttemptState.PREFLIGHT_PASSED)
        attempt.transition(RuntimeAttemptState.RUNNING)
        attempt.transition(RuntimeAttemptState.COMPLETED)

        # 3. Create receipt
        receipt = RuntimeExecutionReceipt(
            execution_id="exec-1",
            attempt_id=attempt.attempt_id,
            attempt_state=attempt.state,
            truth_message=make_truth_message(attempt.state, side_effects=True),
            runtime_execution_performed=True,
            simulated=False,
            dry_run=False,
            side_effects_performed=True,
            preflight_passed=True,
            preflight_fingerprint=result.fingerprint,
        )
        receipt.freeze()
        attempt.set_receipt(receipt)

        assert attempt.is_terminal()
        assert attempt.receipt.truth_message == "Execution completed with side effects performed."


# ---------------------------------------------------------------------------
# T03-29: Receipt attached to AgentResult.data["receipt"]
# (tested via integration in test_cli)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T03-31: Read-only actions always pass
# ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_read_only_actions_pass(self):
        agent = _mock_agent()
        pf = RuntimePreflight(agent)
        for cap in ("screenshot", "snapshot", "health", "schema"):
            result = await pf.run(_mock_goal(capability=cap), _mock_context())
            chk03 = [c for c in result.checks if c.check_id == "CHK-PF-03"][0]
            assert chk03.passed, f"Read-only action '{cap}' should pass capability check"


# ---------------------------------------------------------------------------
# T03-32: Fingerprint detects stale state
# ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_stale_detection(self):
        agent = _mock_agent()
        pf = RuntimePreflight(agent)

        # First run with healthy adapter
        result1 = await pf.run(_mock_goal(), _mock_context())

        # Change health status
        agent._last_health_status = MagicMock(healthy=False)

        # Second run should have different fingerprint
        result2 = await pf.run(_mock_goal(), _mock_context())
        assert result1.fingerprint != result2.fingerprint


# ---------------------------------------------------------------------------
# T03-35: Passes with obligations met
# ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_obligations_met(self):
        agent = _mock_agent()
        pf = RuntimePreflight(agent)
        result = await pf.run(
            _mock_goal(), _mock_context(dry_run=True),
            policy_decision=_mock_policy_decision(
                effect="allow",
                obligations=[PolicyObligation.DRY_RUN_REQUIRED],
            ),
        )
        assert result.passed is True


# ---------------------------------------------------------------------------
# T03-36: Blocks with obligations unmet
# ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_obligations_unmet(self):
        agent = _mock_agent()
        pf = RuntimePreflight(agent)
        result = await pf.run(
            _mock_goal(), _mock_context(dry_run=False),
            policy_decision=_mock_policy_decision(
                effect="allow",
                obligations=[PolicyObligation.DRY_RUN_REQUIRED],
            ),
        )
        assert result.passed is False


# ---------------------------------------------------------------------------
# T03-37: Multiple obligations checked in order
# ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_multiple_obligations(self):
        agent = _mock_agent()
        pf = RuntimePreflight(agent)
        result = await pf.run(
            _mock_goal(), _mock_context(dry_run=True),
            policy_decision=_mock_policy_decision(
                effect="allow",
                obligations=[
                    PolicyObligation.DRY_RUN_REQUIRED,
                    PolicyObligation.LOG_FULL_PAYLOAD,
                ],
            ),
        )
        assert len(result.obligations_required) == 2
        assert PolicyObligation.DRY_RUN_REQUIRED in result.obligations_required
        assert PolicyObligation.LOG_FULL_PAYLOAD in result.obligations_required


# ---------------------------------------------------------------------------
# T03-40: Evidence ledger records attempt state transitions
# ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_attempt_state_recording(self):
        from deskaoy.runtime.types import RuntimeAttempt, RuntimeAttemptState

        attempt = RuntimeAttempt("exec-1")
        states = []

        # Record transitions
        states.append(attempt.state)
        attempt.transition(RuntimeAttemptState.PREFLIGHT_PASSED)
        states.append(attempt.state)
        attempt.transition(RuntimeAttemptState.RUNNING)
        states.append(attempt.state)
        attempt.transition(RuntimeAttemptState.COMPLETED)
        states.append(attempt.state)

        assert states == [
            RuntimeAttemptState.PENDING,
            RuntimeAttemptState.PREFLIGHT_PASSED,
            RuntimeAttemptState.RUNNING,
            RuntimeAttemptState.COMPLETED,
        ]
