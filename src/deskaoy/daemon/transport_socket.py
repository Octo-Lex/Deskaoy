"""Unix domain socket transport for daemon IPC.

Uses ``asyncio.open_unix_connection`` / ``asyncio.start_unix_server``.
Only functional on non-Windows platforms (Linux, macOS).
On Windows, importing succeeds but usage raises ``RuntimeError``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)


def socket_path(name: str = "deskaoy") -> str:
    """Return a Unix domain socket path."""
    return f"/tmp/{name}.sock"


def _check_platform() -> None:
    """Raise if on Windows."""
    if sys.platform == "win32":
        raise RuntimeError(
            "Unix domain socket transport is not available on Windows. "
            "Use named pipe transport instead."
        )


class SocketTransport:
    """Unix domain socket server transport.

    Binds to ``/tmp/<name>.sock`` with user-only permissions (600).
    """

    def __init__(self, socket_path: str) -> None:
        _check_platform()
        self._path = socket_path
        self._server: asyncio.AbstractServer | None = None

    @property
    def path(self) -> str:
        return self._path

    async def start(self, handler: Any) -> None:
        """Start the Unix domain socket server.

        Args:
            handler: An async callable that receives (reader, writer).
        """
        # Remove stale socket file
        if os.path.exists(self._path):
            os.unlink(self._path)

        self._server = await asyncio.start_unix_server(
            handler, path=self._path
        )
        # Set user-only permissions (AUTH-02)
        os.chmod(self._path, 0o600)
        logger.info("Socket transport listening on %s", self._path)

    async def stop(self) -> None:
        """Stop the server and clean up socket file."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if os.path.exists(self._path):
            with contextlib.suppress(OSError):
                os.unlink(self._path)


async def socket_connect(socket_path: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connect to a Unix domain socket."""
    _check_platform()
    return await asyncio.open_unix_connection(socket_path)
