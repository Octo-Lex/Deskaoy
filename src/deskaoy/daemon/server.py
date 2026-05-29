"""DaemonServer — persistent daemon that holds a DesktopAgent instance.

Binds to OS-appropriate transport (named pipe on Windows, Unix socket
elsewhere) and processes JSON-RPC 2.0 requests sequentially using
``asyncio.Lock`` for COM/UIA safety (HB-03).

Features:
- Idle timeout auto-shutdown
- PID-file duplicate detection (AUTH-04)
- Sequential request processing (HB-03)
- Graceful shutdown
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from deskaoy.daemon.config import DaemonConfig
from deskaoy.daemon.protocol import (
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    VALID_METHODS,
    _error_response,
    decode_goal_from_params,
    encode_response,
    json_dumps,
)

logger = logging.getLogger(__name__)


class DaemonServer:
    """Persistent Deskaoy daemon server.

    Holds a single ``DesktopAgent`` instance and serves requests over IPC.
    Requests are processed sequentially (asyncio.Lock) for COM/UIA safety.
    """

    def __init__(
        self,
        config: DaemonConfig | None = None,
        agent: Any = None,
    ) -> None:
        self._config = config or DaemonConfig()
        self._agent = agent
        self._is_running = False
        self._start_time: float = 0.0
        self._calls_served: int = 0
        self._lock = asyncio.Lock()
        self._server: asyncio.AbstractServer | None = None
        self._idle_handle: asyncio.TimerHandle | None = None
        self._pid_file = self._pid_path()

    # ─── Public API ──────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def config(self) -> DaemonConfig:
        return self._config

    @property
    def calls_served(self) -> int:
        return self._calls_served

    async def start(self) -> None:
        """Start the daemon: bind transport, write PID file, begin serving."""
        # AUTH-04: Duplicate detection
        if self._is_pid_file_valid():
            existing_pid = self._read_pid_file()
            raise RuntimeError(
                f"Daemon already running (PID {existing_pid}) on {self._config.socket_path}"
            )

        # Initialize agent if not provided
        if self._agent is None:
            from deskaoy.desktop_agent import DesktopAgent
            self._agent = DesktopAgent()

        # Write PID file
        self._write_pid_file()

        # Start transport
        handler = self._handle_connection
        self._server = await self._create_server(handler)

        self._is_running = True
        self._start_time = time.monotonic()
        self._reset_idle_timeout()
        logger.info(
            "DaemonServer started on %s (PID %d)",
            self._config.socket_path, os.getpid(),
        )

    async def serve_forever(self) -> None:
        """Block until shutdown."""
        await self.start()
        try:
            while self._is_running:
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Gracefully stop the daemon."""
        self._is_running = False
        self._cancel_idle_timeout()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._remove_pid_file()
        logger.info("DaemonServer stopped")

    async def ping(self) -> dict[str, Any]:
        """Return daemon health status."""
        uptime = time.monotonic() - self._start_time if self._start_time else 0.0
        return {"status": "ok", "uptime_s": round(uptime, 1)}

    async def status(self) -> dict[str, Any]:
        """Return detailed daemon status."""
        uptime = time.monotonic() - self._start_time if self._start_time else 0.0
        surface = "none"
        if self._agent is not None and hasattr(self._agent, "_surface"):
            surface = "windows" if self._agent._surface is not None else "none"
        return {
            "healthy": self._is_running,
            "surface": surface,
            "calls_served": self._calls_served,
            "uptime_s": round(uptime, 1),
            "pid": os.getpid(),
        }

    # ─── Connection handling ─────────────────────

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single client connection (newline-delimited JSON-RPC)."""
        try:
            while self._is_running:
                try:
                    line = await asyncio.wait_for(
                        reader.readline(), timeout=self._config.idle_timeout_s
                    )
                except TimeoutError:
                    break
                if not line:
                    break

                # Reset idle timeout on activity
                self._reset_idle_timeout()

                # Parse and process request (sequential — under lock)
                response = await self._process_request(line)

                # Send response
                writer.write(json_dumps(response))
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _process_request(self, raw: bytes) -> dict[str, Any]:
        """Parse and dispatch a single JSON-RPC request.

        Sequential processing via asyncio.Lock (HB-03).
        """
        try:
            msg = json.loads(raw.decode("utf-8").strip())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return _error_response("", -32700, f"Parse error: {exc}")

        request_id = msg.get("id", "")
        method = msg.get("method", "")

        # Validate method
        if not method:
            return _error_response(request_id, INVALID_REQUEST, "Missing 'method' field")

        if method not in VALID_METHODS:
            return _error_response(request_id, METHOD_NOT_FOUND, f"Unknown method: {method}")

        # Sequential processing under lock (HB-03)
        async with self._lock:
            try:
                if method == "ping":
                    result = await self.ping()
                elif method == "status":
                    result = await self.status()
                elif method == "shutdown":
                    result = {"status": "shutting_down"}
                    # Schedule shutdown after response
                    asyncio.get_event_loop().call_soon(
                        lambda: asyncio.ensure_future(self.stop())
                    )
                elif method == "execute":
                    params = msg.get("params", {})
                    result = await self._handle_execute(params)
                else:
                    result = {"error": f"Unhandled method: {method}"}
            except Exception as exc:
                logger.exception("Error processing %s request", method)
                return encode_response(
                    request_id,
                    error={"code": -32603, "message": str(exc)},
                )

        self._calls_served += 1
        return encode_response(request_id, result=result)

    async def _handle_execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle an execute request: deserialize, call agent, serialize."""
        import dataclasses

        goal, context = decode_goal_from_params(params)
        result = await self._agent.execute(goal, context)
        return dataclasses.asdict(result)

    # ─── Transport creation ──────────────────────

    async def _create_server(
        self, handler: Any
    ) -> asyncio.AbstractServer:
        """Create the OS-appropriate transport server."""
        if sys.platform == "win32":
            # Windows: use TCP loopback (see transport_pipe.py note)
            port = 19500 + (hash(self._config.socket_path) % 100)
            server = await asyncio.start_server(
                handler, "127.0.0.1", port
            )
            logger.info("Listening on 127.0.0.1:%d (simulated named pipe)", port)
            return server
        else:
            # Unix: use domain socket
            import os as _os
            path = self._config.socket_path
            if _os.path.exists(path):
                _os.unlink(path)
            server = await asyncio.start_unix_server(handler, path=path)
            _os.chmod(path, 0o600)
            logger.info("Listening on %s", path)
            return server

    # ─── PID file ────────────────────────────────

    def _pid_path(self) -> Path:
        """Return PID file path derived from socket path."""
        safe_name = self._config.socket_path.replace(os.sep, "_").replace(":", "_")
        return Path(tempfile.gettempdir()) / f"deskaoy-daemon-{abs(hash(safe_name))}.pid"

    def _write_pid_file(self) -> None:
        """Write current PID to PID file."""
        self._pid_file.parent.mkdir(parents=True, exist_ok=True)
        self._pid_file.write_text(str(os.getpid()))

    def _read_pid_file(self) -> int | None:
        """Read PID from PID file."""
        try:
            return int(self._pid_file.read_text().strip())
        except (ValueError, FileNotFoundError):
            return None

    def _is_pid_file_valid(self) -> bool:
        """Check if PID file exists and the process is running."""
        pid = self._read_pid_file()
        if pid is None:
            return False
        try:
            os.kill(pid, 0)  # Signal 0 = check if process exists
            return True
        except (ProcessLookupError, PermissionError, OSError):
            # Stale PID file — clean it up
            self._remove_pid_file()
            return False

    def _remove_pid_file(self) -> None:
        """Remove the PID file."""
        try:
            if self._pid_file.exists():
                self._pid_file.unlink()
        except OSError:
            pass

    # ─── Idle timeout ────────────────────────────

    def _reset_idle_timeout(self) -> None:
        """Reset the idle shutdown timer."""
        self._cancel_idle_timeout()
        loop = asyncio.get_event_loop()
        self._idle_handle = loop.call_later(
            self._config.idle_timeout_s,
            lambda: asyncio.ensure_future(self._idle_shutdown()),
        )

    def _cancel_idle_timeout(self) -> None:
        """Cancel the idle shutdown timer."""
        if self._idle_handle is not None:
            self._idle_handle.cancel()
            self._idle_handle = None

    async def _idle_shutdown(self) -> None:
        """Shut down the daemon after idle timeout."""
        logger.info("Idle timeout (%.0fs) reached — shutting down", self._config.idle_timeout_s)
        await self.stop()
