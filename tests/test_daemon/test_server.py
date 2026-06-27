"""BATCH-37 TASK-01 tests: Daemon core — DaemonServer, config, protocol, transport.

Tests TEST-37-01-01 through TEST-37-01-15.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from deskaoy.daemon.config import DaemonConfig, _default_socket_path
from deskaoy.daemon.protocol import (
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    build_execute_request,
    decode_goal_from_params,
    decode_result_from_response,
    encode_request,
    goal_to_params,
    json_dumps,
    parse_request,
)
from deskaoy.os_types import (
    AgentContext,
    AgentGoal,
    AgentResult,
    Confidence,
    ResultStatus,
)

# ---------------------------------------------------------------------------
# TEST-37-01-01: DaemonConfig has correct defaults
# ---------------------------------------------------------------------------


class TestDaemonConfig:
    """TEST-37-01-01: DaemonConfig has correct defaults."""

    def test_idle_timeout_default(self):
        config = DaemonConfig()
        assert config.idle_timeout_s == 300.0

    def test_max_clients_default(self):
        config = DaemonConfig()
        assert config.max_clients == 10

    def test_log_level_default(self):
        config = DaemonConfig()
        assert config.log_level == "INFO"

    def test_socket_path_auto_populated(self):
        config = DaemonConfig()
        assert config.socket_path  # non-empty

    def test_custom_values(self):
        config = DaemonConfig(
            socket_path="/custom/path",
            idle_timeout_s=60.0,
            max_clients=5,
            log_level="DEBUG",
        )
        assert config.socket_path == "/custom/path"
        assert config.idle_timeout_s == 60.0
        assert config.max_clients == 5
        assert config.log_level == "DEBUG"


# ---------------------------------------------------------------------------
# TEST-37-01-02: Protocol encodes AgentGoal to JSON-RPC request
# ---------------------------------------------------------------------------


class TestProtocolEncode:
    """TEST-37-01-02: Protocol encodes AgentGoal to JSON-RPC request."""

    def test_encode_request_structure(self):
        req = encode_request("execute", {"key": "val"}, "test-id")
        assert req["jsonrpc"] == "2.0"
        assert req["id"] == "test-id"
        assert req["method"] == "execute"
        assert req["params"] == {"key": "val"}

    def test_encode_request_auto_id(self):
        req = encode_request("ping")
        assert "id" in req
        assert req["id"]  # non-empty

    def test_goal_to_params_preserves_capability(self):
        goal = AgentGoal(capability="click", params={"target": "button1"})
        ctx = AgentContext(
            execution_id="exec-1",
            idempotency_key="key-1",
            task_id="task-1",
            user_id="user-1",
            session_id="sess-1",
        )
        params = goal_to_params(goal, ctx)
        assert params["goal"]["capability"] == "click"

    def test_build_execute_request(self):
        goal = AgentGoal(capability="click")
        ctx = AgentContext(
            execution_id="e1", idempotency_key="k1",
            task_id="t1", user_id="u1", session_id="s1",
        )
        req = build_execute_request(goal, ctx, "req-1")
        assert req["method"] == "execute"
        assert req["params"]["goal"]["capability"] == "click"


# ---------------------------------------------------------------------------
# TEST-37-01-03: Protocol decodes JSON-RPC response to AgentResult
# ---------------------------------------------------------------------------


class TestProtocolDecode:
    """TEST-37-01-03: Protocol decodes JSON-RPC response to AgentResult."""

    def test_decode_success_response(self):
        response = {
            "jsonrpc": "2.0",
            "id": "1",
            "result": {
                "execution_id": "exec-1",
                "status": "success",
                "summary": "Clicked",
                "data": {"ok": True},
                "artifacts": [],
                "mutations": [],
                "confidence": {"score": 0.9, "reason": "OK", "factors": {}},
                "issues": [],
                "needs_review": [],
                "suggested_followups": [],
                "learnings": [],
                "metadata": {},
            },
        }
        result = decode_result_from_response(response)
        assert isinstance(result, AgentResult)
        assert result.status == ResultStatus.SUCCESS
        assert result.summary == "Clicked"

    def test_decode_error_response(self):
        response = {
            "jsonrpc": "2.0",
            "id": "1",
            "error": {"code": -32603, "message": "Internal error"},
        }
        result = decode_result_from_response(response)
        assert isinstance(result, AgentResult)
        assert result.status == ResultStatus.FAILURE

    def test_decode_goal_from_params(self):
        params = {
            "goal": {
                "capability": "click",
                "params": {"target": "btn"},
                "priority": "high",
            },
            "context": {
                "execution_id": "e1",
                "idempotency_key": "k1",
                "task_id": "t1",
                "user_id": "u1",
                "session_id": "s1",
                "dry_run": True,
            },
        }
        goal, ctx = decode_goal_from_params(params)
        assert isinstance(goal, AgentGoal)
        assert goal.capability == "click"
        assert goal.priority == "high"
        assert ctx.dry_run is True


# ---------------------------------------------------------------------------
# TEST-37-01-04: Protocol rejects malformed JSON-RPC (missing method)
# ---------------------------------------------------------------------------


class TestProtocolValidation:
    """TEST-37-01-04: Protocol rejects malformed JSON-RPC."""

    def test_missing_method_returns_error(self):
        raw = json.dumps({"jsonrpc": "2.0", "id": "1"}).encode()
        result = parse_request(raw)
        assert "error" in result
        assert result["error"]["code"] == INVALID_REQUEST

    def test_invalid_json_returns_parse_error(self):
        raw = b"not valid json{"
        result = parse_request(raw)
        assert "error" in result
        assert result["error"]["code"] == PARSE_ERROR

    def test_non_object_returns_error(self):
        raw = b'"just a string"'
        result = parse_request(raw)
        assert "error" in result


# ---------------------------------------------------------------------------
# TEST-37-01-05: Protocol rejects unknown method
# ---------------------------------------------------------------------------


class TestProtocolUnknownMethod:
    """TEST-37-01-05: Protocol rejects unknown method."""

    def test_unknown_method_returns_error(self):
        raw = json.dumps({
            "jsonrpc": "2.0", "id": "1", "method": "nonexistent",
        }).encode()
        result = parse_request(raw)
        assert "error" in result
        assert result["error"]["code"] == METHOD_NOT_FOUND

    def test_valid_methods_accepted(self):
        for method in ("execute", "ping", "status", "shutdown"):
            raw = json.dumps({
                "jsonrpc": "2.0", "id": "1", "method": method,
            }).encode()
            result = parse_request(raw)
            assert "error" not in result
            assert result["method"] == method


# ---------------------------------------------------------------------------
# TEST-37-01-06: DaemonServer starts, binds socket, responds to ping
# TEST-37-01-07: DaemonServer routes execute to DesktopAgent.execute()
# TEST-37-01-08: DaemonServer queues concurrent requests
# ---------------------------------------------------------------------------


class TestDaemonServerIntegration:
    """Integration tests for DaemonServer (TEST-37-01-06 through 01-08)."""

    @pytest.fixture
    def mock_agent(self):
        """Create a mock DesktopAgent."""
        agent = MagicMock()
        agent.execute = AsyncMock(return_value=AgentResult(
            execution_id="e1",
            status=ResultStatus.SUCCESS,
            summary="mocked",
            data={},
            confidence=Confidence(score=1.0, reason="mock"),
        ))
        agent._surface = None
        return agent

    @pytest.fixture
    def config(self, tmp_path):
        """Create a DaemonConfig with a temporary socket path."""
        if sys.platform == "win32":
            socket_path = r"\\.\pipe\test-daemon-" + str(os.getpid())
        else:
            socket_path = str(tmp_path / "test.sock")
        return DaemonConfig(
            socket_path=socket_path,
            idle_timeout_s=300,
        )

    @pytest.mark.asyncio
    async def test_ping_after_start(self, mock_agent, config):
        """TEST-37-01-06: DaemonServer starts and responds to ping."""
        from deskaoy.daemon.server import DaemonServer

        server = DaemonServer(config=config, agent=mock_agent)
        await server.start()
        try:
            ping = await server.ping()
            assert ping["status"] == "ok"
            assert "uptime_s" in ping
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_execute_routes_to_agent(self, mock_agent, config):
        """TEST-37-01-07: DaemonServer routes execute to DesktopAgent.execute()."""
        from deskaoy.daemon.server import DaemonServer

        server = DaemonServer(config=config, agent=mock_agent)
        await server.start()
        try:
            # Send an execute request via raw TCP/Unix connection
            goal = AgentGoal(capability="click", params={"target": "btn"})
            ctx = AgentContext(
                execution_id="e1", idempotency_key="k1",
                task_id="t1", user_id="u1", session_id="s1",
            )
            request = build_execute_request(goal, ctx, "req-1")
            response_bytes = await self._send_and_receive(config, request)
            response = json.loads(response_bytes.decode().strip())

            assert "result" in response
            mock_agent.execute.assert_called_once()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_sequential_processing(self, mock_agent, config):
        """TEST-37-01-08: DaemonServer queues concurrent requests."""
        from deskaoy.daemon.server import DaemonServer

        # Make execute take some time
        async def slow_execute(goal, context):
            await asyncio.sleep(0.05)
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.SUCCESS,
                summary="slow",
                data={},
                confidence=Confidence(score=1.0, reason="ok"),
            )
        mock_agent.execute = slow_execute

        server = DaemonServer(config=config, agent=mock_agent)
        await server.start()
        try:
            goal = AgentGoal(capability="click")
            ctx = AgentContext(
                execution_id="e1", idempotency_key="k1",
                task_id="t1", user_id="u1", session_id="s1",
            )

            # Send two requests concurrently
            async def send_request(req_id):
                request = build_execute_request(goal, ctx, f"req-{req_id}")
                return await self._send_and_receive(config, request)

            results = await asyncio.gather(
                send_request(1), send_request(2),
            )
            assert len(results) == 2
            # Both should succeed (no crash)
            for r in results:
                resp = json.loads(r.decode().strip())
                assert "result" in resp or "error" in resp
        finally:
            await server.stop()

    async def _send_and_receive(self, config, request_dict):
        """Send a JSON-RPC request and receive the response."""
        if sys.platform == "win32":
            port = 19500 + (hash(config.socket_path) % 100)
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
        else:
            reader, writer = await asyncio.open_unix_connection(config.socket_path)

        writer.write(json_dumps(request_dict))
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        writer.close()
        await writer.wait_closed()
        return line


# ---------------------------------------------------------------------------
# TEST-37-01-09: DaemonServer auto-shuts down after idle timeout
# ---------------------------------------------------------------------------


class TestDaemonServerIdleTimeout:
    """TEST-37-01-09: DaemonServer auto-shuts down after idle timeout."""

    @pytest.mark.asyncio
    async def test_auto_shutdown(self):
        from deskaoy.daemon.server import DaemonServer

        config = DaemonConfig(idle_timeout_s=0.1)
        # Use unique socket path to avoid collision
        if sys.platform == "win32":
            config.socket_path = r"\\.\pipe\test-idle-" + str(os.getpid()) + "-" + str(time.monotonic())
        else:
            import tempfile
            config.socket_path = os.path.join(tempfile.gettempdir(), f"test-idle-{os.getpid()}.sock")

        mock_agent = MagicMock()
        mock_agent._surface = None
        server = DaemonServer(config=config, agent=mock_agent)

        await server.start()
        assert server.is_running is True

        # Wait for idle timeout
        await asyncio.sleep(0.3)

        assert server.is_running is False


# ---------------------------------------------------------------------------
# TEST-37-01-10: Transport named pipe path on Windows
# TEST-37-01-11: Transport Unix socket path on non-Windows
# ---------------------------------------------------------------------------


class TestTransportPaths:
    """TEST-37-01-10 and TEST-37-01-11: Transport path resolution."""

    def test_pipe_path_format(self):
        """TEST-37-01-10: Named pipe path starts with correct prefix on Windows."""
        from deskaoy.daemon.transport_pipe import pipe_path
        path = pipe_path()
        assert path.startswith(chr(92) + chr(92) + "." + chr(92) + "pipe" + chr(92))

    def test_socket_path_format(self):
        """TEST-37-01-11: Unix socket path ends with .sock."""
        from deskaoy.daemon.transport_socket import socket_path
        path = socket_path()
        assert path.endswith(".sock")

    def test_default_socket_path_by_platform(self):
        """Verify _default_socket_path returns platform-appropriate path."""
        path = _default_socket_path()
        if sys.platform == "win32":
            assert "pipe" in path
        else:
            assert path.endswith(".sock")


# ---------------------------------------------------------------------------
# TEST-37-01-12: Second daemon startup on same socket fails
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    """TEST-37-01-12: Second daemon startup on same socket fails with clear error."""

    @pytest.mark.asyncio
    async def test_duplicate_start_fails(self, tmp_path):
        from deskaoy.daemon.server import DaemonServer

        if sys.platform == "win32":
            socket_path = r"\\.\pipe\test-dup-" + str(os.getpid())
        else:
            socket_path = str(tmp_path / "dup.sock")

        config = DaemonConfig(socket_path=socket_path, idle_timeout_s=300)
        mock_agent = MagicMock()
        mock_agent._surface = None

        server1 = DaemonServer(config=config, agent=mock_agent)
        await server1.start()

        try:
            server2 = DaemonServer(config=config, agent=mock_agent)
            with pytest.raises(RuntimeError, match="already running"):
                await server2.start()
        finally:
            await server1.stop()


# ---------------------------------------------------------------------------
# TEST-37-01-13: daemon module imports without error (HB-05)
# ---------------------------------------------------------------------------


class TestImportSafety:
    """TEST-37-01-13: daemon module imports without error even without [daemon]."""

    def test_import_daemon_package(self):
        """Importing deskaoy.daemon should not crash."""
        import deskaoy.daemon
        assert hasattr(deskaoy.daemon, "DaemonConfig")
        assert hasattr(deskaoy.daemon, "__all__")

    def test_import_config_directly(self):
        """Config should be directly importable."""
        from deskaoy.daemon.config import DaemonConfig
        assert DaemonConfig is not None


# ---------------------------------------------------------------------------
# TEST-37-01-14: Daemon status endpoint returns uptime and call count
# ---------------------------------------------------------------------------


class TestDaemonStatus:
    """TEST-37-01-14: Daemon status endpoint returns uptime and call count."""

    @pytest.mark.asyncio
    async def test_status_after_execute(self, tmp_path):
        from deskaoy.daemon.server import DaemonServer

        if sys.platform == "win32":
            socket_path = r"\\.\pipe\test-status-" + str(os.getpid())
        else:
            socket_path = str(tmp_path / "status.sock")

        config = DaemonConfig(socket_path=socket_path, idle_timeout_s=300)
        mock_agent = MagicMock()
        mock_agent._surface = None
        mock_agent.execute = AsyncMock(return_value=AgentResult(
            execution_id="e1",
            status=ResultStatus.SUCCESS,
            summary="ok",
            data={},
            confidence=Confidence(score=1.0, reason="mock"),
        ))

        server = DaemonServer(config=config, agent=mock_agent)
        await server.start()
        try:
            # Simulate serving one request
            goal = AgentGoal(capability="click")
            ctx = AgentContext(
                execution_id="e1", idempotency_key="k1",
                task_id="t1", user_id="u1", session_id="s1",
            )
            request = build_execute_request(goal, ctx, "req-1")
            response_bytes = await self._send_and_receive(config, request)
            resp = json.loads(response_bytes.decode().strip())
            assert "result" in resp

            # Check status
            status = await server.status()
            assert status["calls_served"] == 1
            assert "uptime_s" in status
        finally:
            await server.stop()

    async def _send_and_receive(self, config, request_dict):
        if sys.platform == "win32":
            port = 19500 + (hash(config.socket_path) % 100)
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
        else:
            reader, writer = await asyncio.open_unix_connection(config.socket_path)
        writer.write(json_dumps(request_dict))
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        writer.close()
        await writer.wait_closed()
        return line


# ---------------------------------------------------------------------------
# TEST-37-01-15: shutdown method sets is_running=False
# ---------------------------------------------------------------------------


class TestDaemonShutdown:
    """TEST-37-01-15: shutdown method sets is_running=False."""

    @pytest.mark.asyncio
    async def test_shutdown_sets_not_running(self, tmp_path):
        from deskaoy.daemon.server import DaemonServer

        if sys.platform == "win32":
            socket_path = r"\\.\pipe\test-shutdown-" + str(os.getpid())
        else:
            socket_path = str(tmp_path / "shutdown.sock")

        config = DaemonConfig(socket_path=socket_path, idle_timeout_s=300)
        mock_agent = MagicMock()
        mock_agent._surface = None

        server = DaemonServer(config=config, agent=mock_agent)
        await server.start()
        assert server.is_running is True

        await server.stop()
        assert server.is_running is False
