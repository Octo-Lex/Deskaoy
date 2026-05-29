"""DaemonClient — drop-in replacement for DesktopAgent over IPC.

Implements the same execute(), health(), describe(), schema() method
signatures as DesktopAgent. Connects to the daemon over IPC transport.

Features:
- Auto-starts daemon if not running
- Falls back to direct DesktopAgent if daemon unavailable
- Connection cleanup on close
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import subprocess
import sys
import time
from typing import Any

from deskaoy.daemon.config import DaemonConfig
from deskaoy.daemon.protocol import (
    build_execute_request,
    build_status_request,
    decode_result_from_response,
    json_dumps,
)
from deskaoy.os_types import AgentContext, AgentGoal, AgentResult

logger = logging.getLogger(__name__)


class DaemonUnavailable(Exception):
    """Raised when the daemon cannot be reached and fallback is disabled."""
    pass


class DaemonClient:
    """Drop-in replacement for DesktopAgent that routes through the daemon.

    Implements the same method signatures as DesktopAgent:
    - execute(goal, context) -> AgentResult
    - health() -> HealthStatus
    - describe() -> dict
    - schema() -> dict
    """

    def __init__(
        self,
        config: DaemonConfig | None = None,
        *,
        auto_start: bool = True,
        fallback: bool = True,
    ) -> None:
        self._config = config or DaemonConfig()
        self._auto_start = auto_start
        self._fallback = fallback
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._is_connected = False
        self._fallback_agent: Any = None

    # ─── Public API (DesktopAgent interface) ─────

    async def execute(
        self, goal: AgentGoal, context: AgentContext
    ) -> AgentResult:
        """Execute a goal through the daemon (or fallback to direct)."""
        if self._is_connected:
            try:
                return await self._rpc_execute(goal, context)
            except (ConnectionError, OSError, DaemonUnavailable) as exc:
                logger.warning("Daemon execute failed: %s — falling back", exc)
                self._is_connected = False
                if not self._fallback:
                    raise DaemonUnavailable(str(exc)) from exc

        # Try to connect / auto-start
        if not self._is_connected:
            try:
                await self.connect()
                return await self._rpc_execute(goal, context)
            except (ConnectionError, OSError, DaemonUnavailable) as exc:
                logger.warning("Daemon unavailable: %s", exc)
                self._is_connected = False
                if not self._fallback:
                    raise DaemonUnavailable(str(exc)) from exc

        # Fallback to direct DesktopAgent
        return await self._direct_execute(goal, context)

    async def health(self) -> Any:
        """Proxy health check to daemon (or fallback to direct)."""
        if self._is_connected:
            try:
                response = await self._send_request(build_status_request())
                result = response.get("result", {})
                # Convert daemon status to HealthStatus-like object
                from deskaoy.safety.health import HealthStatus
                return HealthStatus(
                    healthy=result.get("healthy", False),
                    details=result,
                    timestamp=time.monotonic(),
                )
            except (ConnectionError, OSError) as exc:
                logger.warning("Daemon health failed: %s", exc)
                self._is_connected = False

        # Fallback
        agent = self._get_fallback_agent()
        return await agent.health()

    def describe(self) -> dict[str, Any]:
        """Return the discovery document (delegates to fallback agent)."""
        agent = self._get_fallback_agent()
        return agent.describe()

    def schema(self) -> dict[str, Any]:
        """Return the capability schema (delegates to fallback agent)."""
        agent = self._get_fallback_agent()
        return agent.schema()

    # ─── Connection management ───────────────────

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    async def connect(self) -> None:
        """Connect to the daemon, auto-starting if needed."""
        try:
            self._reader, self._writer = await self._ipc_connect()
            self._is_connected = True
            return
        except (ConnectionError, OSError):
            pass

        # Auto-start daemon
        if self._auto_start:
            await self._start_daemon()
            # Retry connection
            self._reader, self._writer = await self._ipc_connect()
            self._is_connected = True

    async def close(self) -> None:
        """Close the connection and clean up."""
        self._is_connected = False
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    # ─── Internal ────────────────────────────────

    async def _ipc_connect(
        self,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Connect to the daemon via OS-appropriate transport."""
        path = self._config.socket_path
        if sys.platform == "win32":
            port = 19500 + (hash(path) % 100)
            return await asyncio.open_connection("127.0.0.1", port)
        else:
            return await asyncio.open_unix_connection(path)

    async def _start_daemon(self) -> None:
        """Start the daemon as a subprocess."""
        cmd = [sys.executable, "-m", "deskaoy.daemon.server",
               "--socket-path", self._config.socket_path]
        logger.info("Auto-starting daemon: %s", " ".join(cmd))

        # Start as detached process
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            # Detach on Windows
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            # Detach on Unix
            start_new_session=sys.platform != "win32",
        )
        logger.info("Daemon started (PID %d)", proc.pid)

        # Wait for daemon to become available
        for _ in range(50):  # 5 seconds max
            await asyncio.sleep(0.1)
            try:
                reader, writer = await self._ipc_connect()
                writer.close()
                await writer.wait_closed()
                return
            except (ConnectionError, OSError):
                continue

        raise DaemonUnavailable("Daemon failed to start within timeout")

    async def _send_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request and read the response."""
        if self._writer is None or self._reader is None:
            raise ConnectionError("Not connected to daemon")

        self._writer.write(json_dumps(request))
        await self._writer.drain()

        # Read response (newline-delimited)
        line = await asyncio.wait_for(self._reader.readline(), timeout=30.0)
        if not line:
            raise ConnectionError("Daemon closed connection")

        return json.loads(line.decode("utf-8").strip())

    async def _rpc_execute(
        self, goal: AgentGoal, context: AgentContext
    ) -> AgentResult:
        """Execute via JSON-RPC to the daemon."""
        request = build_execute_request(goal, context)
        response = await self._send_request(request)
        return decode_result_from_response(response)

    async def _direct_execute(
        self, goal: AgentGoal, context: AgentContext
    ) -> AgentResult:
        """Execute directly via DesktopAgent (fallback path)."""
        agent = self._get_fallback_agent()
        return await agent.execute(goal, context)

    def _get_fallback_agent(self) -> Any:
        """Get or create a fallback DesktopAgent."""
        if self._fallback_agent is None:
            from deskaoy.desktop_agent import DesktopAgent
            self._fallback_agent = DesktopAgent()
        return self._fallback_agent

    def __del__(self) -> None:
        """Cleanup on garbage collection."""
        if self._writer is not None:
            with contextlib.suppress(Exception):
                self._writer.close()
