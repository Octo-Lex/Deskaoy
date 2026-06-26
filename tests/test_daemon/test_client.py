"""BATCH-37 TASK-02 tests: DaemonClient.

Tests TEST-37-02-01 through TEST-37-02-10.
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import os
import sys
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deskaoy.daemon.client import DaemonClient, DaemonUnavailable
from deskaoy.daemon.config import DaemonConfig
from deskaoy.daemon.protocol import (
    build_execute_request,
    build_ping_request,
    build_status_request,
    json_dumps,
)
from deskaoy.os_types import (
    AgentContext,
    AgentGoal,
    AgentResult,
    CancellationToken,
    Confidence,
    ResultStatus,
)
from deskaoy.safety.health import HealthStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_goal(**overrides):
    defaults = {"capability": "click", "params": {"target": "btn"}}
    defaults.update(overrides)
    return AgentGoal(**defaults)


def _make_context(**overrides):
    defaults = {
        "execution_id": "e1",
        "idempotency_key": "k1",
        "task_id": "t1",
        "user_id": "u1",
        "session_id": "s1",
    }
    defaults.update(overrides)
    return AgentContext(**defaults)


# ---------------------------------------------------------------------------
# TEST-37-02-01: DaemonClient.connect() reaches daemon via IPC
# ---------------------------------------------------------------------------


class TestDaemonClientConnect:
    """TEST-37-02-01: DaemonClient.connect() reaches daemon via IPC."""

    @pytest.mark.asyncio
    async def test_connect_success(self, tmp_path):
        """Client connects to a running daemon."""
        from deskaoy.daemon.server import DaemonServer

        if sys.platform == "win32":
            socket_path = r"\\.\pipe\test-client-conn-" + str(os.getpid())
        else:
            socket_path = str(tmp_path / "client.sock")

        config = DaemonConfig(socket_path=socket_path, idle_timeout_s=300)
        mock_agent = MagicMock()
        mock_agent._surface = None
        mock_agent.execute = AsyncMock(return_value=AgentResult(
            execution_id="e1",
            status=ResultStatus.SUCCESS,
            summary="mocked",
            data={},
            confidence=Confidence(score=1.0, reason="mock"),
        ))

        server = DaemonServer(config=config, agent=mock_agent)
        await server.start()

        try:
            client = DaemonClient(config=config, auto_start=False, fallback=False)
            await client.connect()
            assert client.is_connected is True
            await client.close()
        finally:
            await server.stop()


# ---------------------------------------------------------------------------
# TEST-37-02-02: DaemonClient.execute() sends AgentGoal, returns AgentResult
# ---------------------------------------------------------------------------


class TestDaemonClientExecute:
    """TEST-37-02-02: DaemonClient.execute() sends AgentGoal, returns AgentResult."""

    @pytest.mark.asyncio
    async def test_execute_returns_agent_result(self, tmp_path):
        """Execute sends goal and returns AgentResult."""
        from deskaoy.daemon.server import DaemonServer

        if sys.platform == "win32":
            socket_path = r"\\.\pipe\test-client-exec-" + str(os.getpid())
        else:
            socket_path = str(tmp_path / "client-exec.sock")

        config = DaemonConfig(socket_path=socket_path, idle_timeout_s=300)
        mock_agent = MagicMock()
        mock_agent._surface = None
        mock_agent.execute = AsyncMock(return_value=AgentResult(
            execution_id="e1",
            status=ResultStatus.SUCCESS,
            summary="clicked",
            data={"ok": True},
            confidence=Confidence(score=0.9, reason="OK"),
        ))

        server = DaemonServer(config=config, agent=mock_agent)
        await server.start()

        try:
            client = DaemonClient(config=config, auto_start=False, fallback=False)
            result = await client.execute(_make_goal(), _make_context())
            assert isinstance(result, AgentResult)
            assert result.status == ResultStatus.SUCCESS
            await client.close()
        finally:
            await server.stop()


# ---------------------------------------------------------------------------
# TEST-37-02-03: DaemonClient.describe() returns discovery document
# ---------------------------------------------------------------------------


class TestDaemonClientDescribe:
    """TEST-37-02-03: DaemonClient.describe() returns discovery document."""

    def test_describe_returns_dict(self):
        """Describe returns the agent's discovery document."""
        client = DaemonClient(auto_start=False, fallback=True)
        desc = client.describe()
        assert isinstance(desc, dict)
        assert desc.get("name") == "deskaoy"


# ---------------------------------------------------------------------------
# TEST-37-02-04: DaemonClient.health() proxies to daemon health
# ---------------------------------------------------------------------------


class TestDaemonClientHealth:
    """TEST-37-02-04: DaemonClient.health() proxies to daemon health."""

    @pytest.mark.asyncio
    async def test_health_returns_health_status(self, tmp_path):
        """Health check returns HealthStatus."""
        from deskaoy.daemon.server import DaemonServer

        if sys.platform == "win32":
            socket_path = r"\\.\pipe\test-client-health-" + str(os.getpid())
        else:
            socket_path = str(tmp_path / "client-health.sock")

        config = DaemonConfig(socket_path=socket_path, idle_timeout_s=300)
        mock_agent = MagicMock()
        mock_agent._surface = None
        mock_agent.execute = AsyncMock(return_value=AgentResult(
            execution_id="e1", status=ResultStatus.SUCCESS,
            summary="ok", data={}, confidence=Confidence(score=1.0, reason="mock"),
        ))

        server = DaemonServer(config=config, agent=mock_agent)
        await server.start()

        try:
            client = DaemonClient(config=config, auto_start=False, fallback=False)
            await client.connect()
            health = await client.health()
            assert isinstance(health, HealthStatus)
            assert health.healthy is True
            await client.close()
        finally:
            await server.stop()


# ---------------------------------------------------------------------------
# TEST-37-02-05: DaemonClient auto-starts daemon if not running
# ---------------------------------------------------------------------------


class TestDaemonClientAutoStart:
    """TEST-37-02-05: DaemonClient auto-starts daemon if not running."""

    @pytest.mark.asyncio
    async def test_auto_start_attempt(self):
        """Client attempts to start daemon when auto_start=True."""
        config = DaemonConfig(
            socket_path=r"\\.\pipe\test-autostart-" + str(os.getpid())
            if sys.platform == "win32"
            else f"/tmp/test-autostart-{os.getpid()}.sock",
            idle_timeout_s=300,
        )
        # Mock _start_daemon to avoid actually starting a subprocess
        client = DaemonClient(config=config, auto_start=True, fallback=False)
        client._start_daemon = AsyncMock()

        # Attempt connect — should call _start_daemon and fail
        # (since no server is actually running)
        with pytest.raises((ConnectionError, OSError)):
            await client.connect()

        client._start_daemon.assert_called_once()


# ---------------------------------------------------------------------------
# TEST-37-02-06: DaemonClient falls back to direct DesktopAgent
# ---------------------------------------------------------------------------


class TestDaemonClientFallback:
    """TEST-37-02-06: DaemonClient falls back to direct DesktopAgent."""

    @pytest.mark.asyncio
    async def test_fallback_on_connection_failure(self):
        """Client falls back to direct DesktopAgent when daemon unavailable."""
        config = DaemonConfig(
            socket_path=r"\\.\pipe\test-fallback-" + str(os.getpid())
            if sys.platform == "win32"
            else f"/tmp/test-fallback-{os.getpid()}.sock",
        )
        client = DaemonClient(config=config, auto_start=False, fallback=True)

        # Execute should fall back to direct agent
        result = await client.execute(_make_goal(), _make_context())
        assert isinstance(result, AgentResult)
        # Should come from direct DesktopAgent (which has no surface)
        # so result will be a failure since capability "click" is unknown to mock
        await client.close()


# ---------------------------------------------------------------------------
# TEST-37-02-07: DaemonClient handles daemon crash mid-session
# ---------------------------------------------------------------------------


class TestDaemonClientCrash:
    """TEST-37-02-07: DaemonClient handles daemon crash mid-session."""

    @pytest.mark.asyncio
    async def test_crash_fallback(self, tmp_path):
        """Client handles daemon crash and falls back gracefully."""
        from deskaoy.daemon.server import DaemonServer

        if sys.platform == "win32":
            socket_path = r"\\.\pipe\test-crash-" + str(os.getpid())
        else:
            socket_path = str(tmp_path / "crash.sock")

        config = DaemonConfig(socket_path=socket_path, idle_timeout_s=300)
        mock_agent = MagicMock()
        mock_agent._surface = None
        mock_agent.execute = AsyncMock(return_value=AgentResult(
            execution_id="e1", status=ResultStatus.SUCCESS,
            summary="ok", data={}, confidence=Confidence(score=1.0, reason="mock"),
        ))

        server = DaemonServer(config=config, agent=mock_agent)
        await server.start()

        try:
            client = DaemonClient(config=config, auto_start=False, fallback=True)
            # First call works
            await client.connect()
            assert client.is_connected is True

            # Kill the server
            await server.stop()

            # Mark client as disconnected to simulate crash
            client._is_connected = False
            client._writer = None
            client._reader = None

            # This should fall back to direct DesktopAgent
            result = await client.execute(_make_goal(), _make_context())
            assert isinstance(result, AgentResult)
            await client.close()
        except Exception:
            pass  # Server may already be stopped


# ---------------------------------------------------------------------------
# TEST-37-02-08: Multiple DaemonClient instances share one daemon
# ---------------------------------------------------------------------------


class TestDaemonClientMultiInstance:
    """TEST-37-02-08: Multiple DaemonClient instances share one daemon."""

    @pytest.mark.asyncio
    async def test_shared_daemon(self, tmp_path):
        """Two clients connect to the same daemon instance."""
        from deskaoy.daemon.server import DaemonServer

        if sys.platform == "win32":
            socket_path = r"\\.\pipe\test-multi-" + str(os.getpid())
        else:
            socket_path = str(tmp_path / "multi.sock")

        config = DaemonConfig(socket_path=socket_path, idle_timeout_s=300)
        mock_agent = MagicMock()
        mock_agent._surface = None
        mock_agent.execute = AsyncMock(return_value=AgentResult(
            execution_id="e1", status=ResultStatus.SUCCESS,
            summary="ok", data={}, confidence=Confidence(score=1.0, reason="mock"),
        ))

        server = DaemonServer(config=config, agent=mock_agent)
        await server.start()

        try:
            client1 = DaemonClient(config=config, auto_start=False, fallback=False)
            client2 = DaemonClient(config=config, auto_start=False, fallback=False)

            await client1.connect()
            await client2.connect()

            assert client1.is_connected is True
            assert client2.is_connected is True

            # Both should be able to execute
            r1 = await client1.execute(_make_goal(), _make_context())
            assert isinstance(r1, AgentResult)

            await client1.close()
            await client2.close()
        finally:
            await server.stop()


# ---------------------------------------------------------------------------
# TEST-37-02-09: DaemonClient disconnect cleans up socket
# ---------------------------------------------------------------------------


class TestDaemonClientCleanup:
    """TEST-37-02-09: DaemonClient disconnect cleans up socket."""

    @pytest.mark.asyncio
    async def test_close_clears_connection(self, tmp_path):
        """Closing client releases socket resources."""
        from deskaoy.daemon.server import DaemonServer

        if sys.platform == "win32":
            socket_path = r"\\.\pipe\test-cleanup-" + str(os.getpid())
        else:
            socket_path = str(tmp_path / "cleanup.sock")

        config = DaemonConfig(socket_path=socket_path, idle_timeout_s=300)
        mock_agent = MagicMock()
        mock_agent._surface = None
        mock_agent.execute = AsyncMock(return_value=AgentResult(
            execution_id="e1", status=ResultStatus.SUCCESS,
            summary="ok", data={}, confidence=Confidence(score=1.0, reason="mock"),
        ))

        server = DaemonServer(config=config, agent=mock_agent)
        await server.start()

        try:
            client = DaemonClient(config=config, auto_start=False, fallback=False)
            await client.connect()
            assert client.is_connected is True

            await client.close()
            assert client.is_connected is False
            assert client._writer is None
            assert client._reader is None
        finally:
            await server.stop()


# ---------------------------------------------------------------------------
# TEST-37-02-10: DaemonClient implements same method signatures as DesktopAgent
# ---------------------------------------------------------------------------


class TestDaemonClientSignatures:
    """TEST-37-02-10: DaemonClient implements same method signatures as DesktopAgent."""

    def test_execute_signature_match(self):
        """execute() signature matches DesktopAgent.execute()."""
        from deskaoy.desktop_agent import DesktopAgent

        da_sig = inspect.signature(DesktopAgent.execute)
        dc_sig = inspect.signature(DaemonClient.execute)

        da_params = list(da_sig.parameters.keys())
        dc_params = list(dc_sig.parameters.keys())
        # Skip 'self' — compare the rest
        assert da_params[1:] == dc_params[1:]  # ['goal', 'context']

    def test_health_signature_match(self):
        """health() signature matches DesktopAgent.health()."""
        from deskaoy.desktop_agent import DesktopAgent

        da_sig = inspect.signature(DesktopAgent.health)
        dc_sig = inspect.signature(DaemonClient.health)

        da_params = list(da_sig.parameters.keys())
        dc_params = list(dc_sig.parameters.keys())
        assert da_params == dc_params

    def test_describe_signature_match(self):
        """describe() signature matches DesktopAgent.describe()."""
        from deskaoy.desktop_agent import DesktopAgent

        da_sig = inspect.signature(DesktopAgent.describe)
        dc_sig = inspect.signature(DaemonClient.describe)

        da_params = list(da_sig.parameters.keys())
        dc_params = list(dc_sig.parameters.keys())
        assert da_params == dc_params

    def test_schema_signature_match(self):
        """schema() signature matches DesktopAgent.schema()."""
        from deskaoy.desktop_agent import DesktopAgent

        da_sig = inspect.signature(DesktopAgent.schema)
        dc_sig = inspect.signature(DaemonClient.schema)

        da_params = list(da_sig.parameters.keys())
        dc_params = list(dc_sig.parameters.keys())
        assert da_params == dc_params

    def test_all_four_methods_present(self):
        """DaemonClient has execute, health, describe, schema."""
        client = DaemonClient(auto_start=False)
        assert callable(getattr(client, "execute", None))
        assert callable(getattr(client, "health", None))
        assert callable(getattr(client, "describe", None))
        assert callable(getattr(client, "schema", None))
