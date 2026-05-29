"""Deskaoy daemon package.

Provides DaemonServer, DaemonClient, and DaemonConfig for persistent
daemon operation. The daemon holds a DesktopAgent instance initialized
once, then serves commands over IPC (named pipe on Windows, Unix domain
socket elsewhere).

HB-05: This module is importable without optional dependencies.
Only attempting to start/connect the daemon may fail if stdlib
asyncio has issues (shouldn't happen on Python 3.11+).
"""

from deskaoy.daemon.config import DaemonConfig

__all__ = [
    "DaemonConfig",
    "DaemonServer",
    "DaemonClient",
]


def __getattr__(name: str):
    """Lazy imports — DaemonServer and DaemonClient only loaded when accessed."""
    if name == "DaemonServer":
        from deskaoy.daemon.server import DaemonServer
        return DaemonServer
    if name == "DaemonClient":
        from deskaoy.daemon.client import DaemonClient
        return DaemonClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
