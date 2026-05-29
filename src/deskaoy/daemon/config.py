"""Daemon configuration — DaemonConfig dataclass with sensible defaults."""

from __future__ import annotations

import sys
from dataclasses import dataclass


def _default_socket_path() -> str:
    """Return OS-appropriate default socket path."""
    if sys.platform == "win32":
        return r"\\.\pipe\deskaoy"
    return "/tmp/deskaoy.sock"


@dataclass
class DaemonConfig:
    """Configuration for the Deskaoy daemon.

    Attributes:
        socket_path: Named pipe path on Windows, .sock path on Unix.
        idle_timeout_s: Auto-shutdown after this many seconds idle.
        max_clients: Maximum concurrent connections.
        log_level: Logging level string.
    """

    socket_path: str = ""
    idle_timeout_s: float = 300.0
    max_clients: int = 10
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if not self.socket_path:
            self.socket_path = _default_socket_path()
