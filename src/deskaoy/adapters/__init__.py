"""Adapter factory — create the correct SurfaceAdapter for the current platform.

Usage:
    from deskaoy.adapters import create_adapter
    adapter = create_adapter()  # Returns WindowsAdapter, LinuxAdapter, etc.
"""

from __future__ import annotations

import platform

from deskaoy.cascade.protocol import SurfaceAdapter


def create_adapter(**kwargs) -> SurfaceAdapter:
    """Create a SurfaceAdapter for the current platform.

    Returns:
        WindowsAdapter on Windows
        LinuxAdapter on Linux (requires python3-atspi)
        Raises ImportError for unsupported platforms

    Raises:
        ImportError: If platform-specific dependencies are missing.
    """
    system = platform.system()

    if system == "Windows":
        from deskaoy.adapters.windows import WindowsAdapter
        return WindowsAdapter(**kwargs)

    if system == "Linux":
        try:
            from deskaoy.adapters.linux import LinuxAdapter
            return LinuxAdapter(**kwargs)
        except ImportError as exc:
            raise ImportError(
                "Linux adapter requires python3-atspi. "
                "Install with: sudo apt install python3-atspi"
            ) from exc

    raise ImportError(
        f"Unsupported platform: {system}. "
        f"Supported: Windows, Linux"
    )
