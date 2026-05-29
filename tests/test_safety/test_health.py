"""Tests for HealthCheck — readiness/liveness probe."""

import asyncio
from unittest.mock import MagicMock, AsyncMock, PropertyMock

import pytest

from deskaoy.safety.health import HealthCheck, HealthStatus
from deskaoy.safety.cost_tracker import CostTracker


def _make_agent(
    surface=None,
    llm=None,
    policy_connected=True,
    storage_resolver=None,
    circuit_open=False,
):
    """Create a mock agent with configurable subsystems."""
    agent = MagicMock()

    # Surface
    if surface is None:
        surface = MagicMock()
        surface.is_reachable.return_value = True
    agent._surface = surface

    # LLM
    if llm is None:
        llm = MagicMock()
        llm.is_ready.return_value = True
    agent._llm = llm

    # Policy bridge
    policy = MagicMock()
    policy.is_connected = policy_connected
    agent._policy_bridge = policy

    # Storage resolver
    if storage_resolver is None:
        sr = MagicMock()
        p = MagicMock()
        p.exists.return_value = True
        sr.resolve.return_value = p
        agent._storage_resolver = sr
    else:
        agent._storage_resolver = storage_resolver

    # Recovery bridge + circuit breaker
    cb = MagicMock()
    cb.is_open.return_value = circuit_open
    cb.failure_count = 0
    recovery = MagicMock()
    recovery.circuit_breaker = cb
    agent._recovery_bridge = recovery

    return agent


class TestHealthStatus:
    def test_construction(self):
        hs = HealthStatus(healthy=True, checks={}, details={}, timestamp=1.0)
        assert hs.healthy is True

    def test_defaults(self):
        hs = HealthStatus(healthy=False)
        assert hs.checks == {}
        assert hs.details == {}


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_all_checks_pass(self):
        agent = _make_agent()
        hc = HealthCheck(agent)
        result = await hc.check()
        assert result.healthy is True
        assert all(v is not False for v in result.checks.values())

    @pytest.mark.asyncio
    async def test_surface_missing_returns_na(self):
        """Surface not configured should return N/A (None), not unhealthy."""
        agent = _make_agent()
        agent._surface = None
        hc = HealthCheck(agent)
        result = await hc.check()
        assert result.checks["surface"] is None  # N/A — optional subsystem
        assert result.healthy is True  # N/A doesn't make overall unhealthy

    @pytest.mark.asyncio
    async def test_llm_not_ready(self):
        llm = MagicMock()
        llm.is_ready.return_value = False
        agent = _make_agent()
        agent._llm = llm
        hc = HealthCheck(agent)
        result = await hc.check()
        assert result.checks["llm"] is False

    @pytest.mark.asyncio
    async def test_circuit_breaker_open(self):
        agent = _make_agent(circuit_open=True)
        hc = HealthCheck(agent)
        result = await hc.check()
        assert result.checks["circuit_breaker"] is False
        assert result.healthy is False

    @pytest.mark.asyncio
    async def test_budget_exceeded(self):
        agent = _make_agent()
        ct = CostTracker(budget_usd=0.0001)
        ct.record("openai", "gpt-4o", 100_000, 100_000)
        hc = HealthCheck(agent, cost_tracker=ct)
        result = await hc.check()
        assert result.checks["cost_budget"] is False
        assert result.healthy is False

    @pytest.mark.asyncio
    async def test_storage_not_configured_returns_na(self):
        """Storage not configured should return N/A (None), not fail."""
        agent = _make_agent(storage_resolver=None)
        agent._storage_resolver = None
        hc = HealthCheck(agent)
        result = await hc.check()
        assert result.checks["storage"] is None  # N/A — optional subsystem

    @pytest.mark.asyncio
    async def test_details_populated(self):
        agent = _make_agent()
        hc = HealthCheck(agent)
        result = await hc.check()
        assert len(result.details) == 14  # 9 original + 4 service (BATCH-26) + 1 macos_adapter (BATCH-33)
        for key in ["surface", "llm", "policy", "storage", "circuit_breaker", "cost_budget", "key_blocklist", "sensitive_apps", "snapshot_store", "menu_service", "taskbar_service", "dialog_service", "desktop_service", "macos_adapter"]:
            assert key in result.details

    @pytest.mark.asyncio
    async def test_timestamp_is_recent(self):
        import time
        before = time.monotonic()
        agent = _make_agent()
        hc = HealthCheck(agent)
        result = await hc.check()
        after = time.monotonic()
        assert before <= result.timestamp <= after
