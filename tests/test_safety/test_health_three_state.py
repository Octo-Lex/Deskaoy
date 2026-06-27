"""Tests for 3-state health check (pass/na/fail)."""

from __future__ import annotations

import pytest

from deskaoy.safety.health import HealthCheck, HealthStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _StubAgent:
    """Minimal agent stub with no optional subsystems."""

    def __init__(self, **overrides):
        self._surface = overrides.get("surface")
        self._llm = overrides.get("llm")
        self._policy_bridge = overrides.get("policy_bridge")
        self._storage_resolver = overrides.get("storage_resolver")
        self._recovery_bridge = overrides.get("recovery_bridge")


class _StubSurface:
    """Surface adapter stub."""

    def is_reachable(self):
        return True


class _BrokenSurface:
    """Surface adapter that is unreachable."""

    def is_reachable(self):
        return False


class _StubLLM:
    """LLM client stub."""

    def is_ready(self):
        return True


class _BrokenLLM:
    """LLM client that is not ready."""

    def is_ready(self):
        return False


class _StubPolicyBridge:
    """Policy bridge stub."""

    is_connected = True


class _StubStorage:
    """Storage resolver stub."""

    def resolve_action_memory(self):
        from pathlib import Path
        return Path(".")


# ---------------------------------------------------------------------------
# Tests — bare agent (all optional subsystems N/A)
# ---------------------------------------------------------------------------


class TestThreeStateBareAgent:
    """Bare agent with no optional subsystems should be HEALTHY (all N/A)."""

    @pytest.mark.asyncio
    async def test_bare_agent_healthy(self):
        agent = _StubAgent()
        hc = HealthCheck(agent)
        status = await hc.check()
        # All optional subsystems are N/A, built-in ones pass
        assert status.healthy is True

    @pytest.mark.asyncio
    async def test_surface_na_when_not_configured(self):
        agent = _StubAgent()
        hc = HealthCheck(agent)
        status = await hc.check()
        assert status.checks["surface"] is None  # N/A
        assert "not configured" in status.details["surface"].lower()

    @pytest.mark.asyncio
    async def test_llm_na_when_not_configured(self):
        agent = _StubAgent()
        hc = HealthCheck(agent)
        status = await hc.check()
        assert status.checks["llm"] is None  # N/A

    @pytest.mark.asyncio
    async def test_policy_na_when_not_configured(self):
        agent = _StubAgent()
        hc = HealthCheck(agent)
        status = await hc.check()
        assert status.checks["policy"] is None  # N/A

    @pytest.mark.asyncio
    async def test_storage_na_when_not_configured(self):
        agent = _StubAgent()
        hc = HealthCheck(agent)
        status = await hc.check()
        assert status.checks["storage"] is None  # N/A

    @pytest.mark.asyncio
    async def test_builtins_pass(self):
        """Key blocklist and sensitive apps should always pass."""
        agent = _StubAgent()
        hc = HealthCheck(agent)
        status = await hc.check()
        assert status.checks["key_blocklist"] is True
        assert status.checks["sensitive_apps"] is True

    @pytest.mark.asyncio
    async def test_circuit_breaker_na_passes(self):
        """Circuit breaker check should pass when no recovery bridge."""
        agent = _StubAgent()
        hc = HealthCheck(agent)
        status = await hc.check()
        assert status.checks["circuit_breaker"] is True


# ---------------------------------------------------------------------------
# Tests — configured subsystems
# ---------------------------------------------------------------------------


class TestThreeStateConfiguredAgent:
    """Agent with configured subsystems should report True/False."""

    @pytest.mark.asyncio
    async def test_surface_passes_when_reachable(self):
        agent = _StubAgent(surface=_StubSurface())
        hc = HealthCheck(agent)
        status = await hc.check()
        assert status.checks["surface"] is True
        assert "available" in status.details["surface"].lower()

    @pytest.mark.asyncio
    async def test_surface_fails_when_unreachable(self):
        agent = _StubAgent(surface=_BrokenSurface())
        hc = HealthCheck(agent)
        status = await hc.check()
        assert status.checks["surface"] is False
        assert "not reachable" in status.details["surface"].lower()
        # Overall should be unhealthy because a configured subsystem failed
        assert status.healthy is False

    @pytest.mark.asyncio
    async def test_llm_passes_when_ready(self):
        agent = _StubAgent(llm=_StubLLM())
        hc = HealthCheck(agent)
        status = await hc.check()
        assert status.checks["llm"] is True

    @pytest.mark.asyncio
    async def test_llm_fails_when_not_ready(self):
        agent = _StubAgent(llm=_BrokenLLM())
        hc = HealthCheck(agent)
        status = await hc.check()
        assert status.checks["llm"] is False
        assert status.healthy is False

    @pytest.mark.asyncio
    async def test_policy_passes_when_connected(self):
        agent = _StubAgent(policy_bridge=_StubPolicyBridge())
        hc = HealthCheck(agent)
        status = await hc.check()
        assert status.checks["policy"] is True

    @pytest.mark.asyncio
    async def test_storage_passes_when_available(self):
        agent = _StubAgent(storage_resolver=_StubStorage())
        hc = HealthCheck(agent)
        status = await hc.check()
        assert status.checks["storage"] is True


# ---------------------------------------------------------------------------
# Tests — mixed states
# ---------------------------------------------------------------------------


class TestThreeStateMixed:
    """Mix of pass, N/A, and fail."""

    @pytest.mark.asyncio
    async def test_na_does_not_break_health(self):
        """N/A checks should not make the overall status unhealthy."""
        agent = _StubAgent(surface=_StubSurface())  # surface=pass, llm=NA
        hc = HealthCheck(agent)
        status = await hc.check()
        assert status.checks["surface"] is True
        assert status.checks["llm"] is None  # N/A
        assert status.healthy is True

    @pytest.mark.asyncio
    async def test_fail_overrides_na(self):
        """One failure should make overall unhealthy regardless of N/A checks."""
        agent = _StubAgent(surface=_BrokenSurface())
        hc = HealthCheck(agent)
        status = await hc.check()
        assert status.checks["surface"] is False
        assert status.checks["llm"] is None  # N/A
        assert status.healthy is False

    @pytest.mark.asyncio
    async def test_all_pass_with_na(self):
        """All subsystems pass or N/A → healthy."""
        agent = _StubAgent(
            surface=_StubSurface(),
            llm=_StubLLM(),
            policy_bridge=_StubPolicyBridge(),
            storage_resolver=_StubStorage(),
        )
        hc = HealthCheck(agent)
        status = await hc.check()
        assert all(v is not False for v in status.checks.values())
        assert status.healthy is True


# ---------------------------------------------------------------------------
# Tests — HealthStatus dataclass
# ---------------------------------------------------------------------------


class TestHealthStatusDataclass:

    def test_health_status_defaults(self):
        status = HealthStatus(healthy=True)
        assert status.checks == {}
        assert status.details == {}
        assert status.timestamp == 0.0

    def test_health_status_with_checks(self):
        status = HealthStatus(
            healthy=True,
            checks={"surface": True, "llm": None, "policy": False},
            details={"surface": "ok", "llm": "N/A", "policy": "broken"},
            timestamp=123.0,
        )
        assert status.checks["surface"] is True
        assert status.checks["llm"] is None
        assert status.checks["policy"] is False
        assert status.healthy is True
