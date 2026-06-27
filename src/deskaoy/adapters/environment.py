"""Environment Interface — UI-TARS pattern for swappable desktop environments.

Defines the Environment protocol that decouples agent logic from the
underlying desktop environment. Swap between LocalDesktop, DockerDesktop,
and RemoteVM without changing agent code.

Lifecycle: initialize → on_before_tool → on_after_tool → on_dispose

Inspired by UI-TARS's Environment abstraction.

Platform detection (BATCH-33):
  - Environment.is_macos — True on macOS, False elsewhere
  - Environment.is_windows — True on Windows, False elsewhere
  - create_adapter() — factory returning the right SurfaceAdapter
"""

from __future__ import annotations

import logging
import os
import platform
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class EnvironmentState(StrEnum):
    CREATED = "created"
    INITIALIZING = "initializing"
    READY = "ready"
    BUSY = "busy"
    ERROR = "error"
    DISPOSED = "disposed"


@dataclass
class EnvironmentInfo:
    """Metadata about the current environment."""
    name: str
    type: str  # "local", "docker", "remote"
    os_name: str = ""
    os_version: str = ""
    screen_width: int = 1920
    screen_height: int = 1080
    dpi: float = 96.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionResult:
    """Result of an environment action (re-exported for convenience)."""
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Environment Protocol
# ---------------------------------------------------------------------------

class Environment(ABC):
    """Base class for desktop environments.

    Defines the lifecycle and action interface that all environments
    must implement. The agent interacts with the environment through
    this protocol, never directly with the OS.

    Lifecycle:
        initialize() → ready
        on_before_tool() → (execute tool) → on_after_tool()
        on_dispose() → disposed
    """

    def __init__(self) -> None:
        self._state = EnvironmentState.CREATED
        self._info: EnvironmentInfo | None = None

    @property
    def state(self) -> EnvironmentState:
        return self._state

    @property
    def info(self) -> EnvironmentInfo | None:
        return self._info

    @property
    def is_linux(self) -> bool:
        """Check if the current platform is Linux."""
        return platform.system() == "Linux"

    @property
    def is_windows(self) -> bool:
        """Check if the current platform is Windows."""
        return platform.system() == "Windows"

    @property
    def is_macos(self) -> bool:
        """Check if the current platform is macOS."""
        return platform.system() == "Darwin"

    # ------------------------------------------------------------------
    # Platform detection (BATCH-33, BATCH-34)
    # ------------------------------------------------------------------

    @staticmethod
    def create_adapter(**kwargs: Any) -> Any:
        """Factory: create the appropriate SurfaceAdapter for this platform.

        Returns:
            MacOSAdapter on macOS (if pyobjc available)
            WindowsAdapter on Windows (if pywin32 available)
            LinuxAdapter on Linux (if python3-atspi available)

        Raises:
            ImportError: If the required platform dependencies are missing.
        """
        if sys.platform == "darwin":
            # macOS adapter exists but is experimental — the CGEvent/Quartz
            # code paths are untested without macOS hardware. Do not silently
            # select it; require explicit opt-in via DESKTOP_AGENT_MACOS=1.
            if os.environ.get("DESKTOP_AGENT_MACOS", "").lower() not in ("1", "true", "yes"):
                raise ImportError(
                    "macOS adapter is experimental and untested without macOS "
                    "hardware. To opt in, set DESKTOP_AGENT_MACOS=1 and install "
                    "pyobjc-framework-ApplicationServices pyobjc-framework-Quartz."
                )
            try:
                from deskaoy.adapters.macos import MacOSAdapter
                return MacOSAdapter(**kwargs)
            except ImportError:
                raise ImportError(
                    "macOS adapter requires pyobjc. "
                    "Install with: pip install pyobjc-framework-ApplicationServices "
                    "pyobjc-framework-Quartz"
                ) from None
        elif sys.platform == "win32":
            try:
                from deskaoy.adapters.windows import WindowsAdapter
                return WindowsAdapter(**kwargs)
            except ImportError:
                raise ImportError(
                    "Windows adapter requires pywin32. "
                    "Install with: pip install pywin32"
                ) from None
        elif sys.platform == "linux":
            try:
                from deskaoy.adapters.linux import LinuxAdapter
                return LinuxAdapter(**kwargs)
            except ImportError:
                raise ImportError(
                    "Linux adapter requires python3-atspi. "
                    "Install with: sudo apt install python3-atspi"
                ) from None
        else:
            raise ImportError(
                f"No surface adapter available for platform: {sys.platform}"
            )

    @abstractmethod
    async def initialize(self) -> EnvironmentInfo:
        """Initialize the environment. Called once before any actions."""
        ...

    @abstractmethod
    async def on_before_tool(self, tool_name: str, params: dict) -> dict:
        """Pre-tool hook. May modify params. Returns (possibly modified) params."""
        ...

    @abstractmethod
    async def on_after_tool(self, tool_name: str, params: dict, result: Any) -> None:
        """Post-tool hook. May inspect or log the result."""
        ...

    @abstractmethod
    async def on_dispose(self) -> None:
        """Clean up the environment. Called once when shutting down."""
        ...

    async def screenshot(self) -> bytes:
        """Take a screenshot of the environment."""
        raise NotImplementedError(f"{type(self).__name__} does not support screenshots")

    async def execute_action(self, action: str, **kwargs: Any) -> Any:
        """Execute a generic action in the environment."""
        raise NotImplementedError(f"{type(self).__name__} does not support execute_action")


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

class LocalDesktop(Environment):
    """Local desktop environment — direct access to the host OS.

    Uses the SurfaceAdapter for actual interactions.
    """

    def __init__(self, adapter: Any = None) -> None:
        super().__init__()
        self._adapter = adapter

    async def initialize(self) -> EnvironmentInfo:
        self._state = EnvironmentState.INITIALIZING
        import platform

        screen_w, screen_h = 1920, 1080
        try:
            if platform.system() == "Windows":
                import ctypes
                user32 = ctypes.windll.user32
                screen_w = user32.GetSystemMetrics(0)
                screen_h = user32.GetSystemMetrics(1)
        except Exception:
            pass

        self._info = EnvironmentInfo(
            name="local-desktop",
            type="local",
            os_name=platform.system(),
            os_version=platform.version(),
            screen_width=screen_w,
            screen_height=screen_h,
        )
        self._state = EnvironmentState.READY
        return self._info

    async def on_before_tool(self, tool_name: str, params: dict) -> dict:
        self._state = EnvironmentState.BUSY
        return params

    async def on_after_tool(self, tool_name: str, params: dict, result: Any) -> None:
        self._state = EnvironmentState.READY

    async def on_dispose(self) -> None:
        self._state = EnvironmentState.DISPOSED

    async def screenshot(self) -> bytes:
        if self._adapter:
            result = await self._adapter.screenshot()
            if isinstance(result, bytes):
                return result
        return b""


class DockerDesktop(Environment):
    """Docker-based desktop environment.

    Connects to a VNC/noVNC container running a desktop environment.
    Uses X11 forwarding or VNC for screen capture.
    """

    def __init__(self, container_id: str = "", vnc_port: int = 5900) -> None:
        super().__init__()
        self._container_id = container_id
        self._vnc_port = vnc_port

    async def initialize(self) -> EnvironmentInfo:
        self._state = EnvironmentState.INITIALIZING
        self._info = EnvironmentInfo(
            name=f"docker-{self._container_id[:12]}",
            type="docker",
            os_name="Linux",
            screen_width=1920,
            screen_height=1080,
            metadata={"container_id": self._container_id, "vnc_port": self._vnc_port},
        )
        self._state = EnvironmentState.READY
        return self._info

    async def on_before_tool(self, tool_name: str, params: dict) -> dict:
        self._state = EnvironmentState.BUSY
        return params

    async def on_after_tool(self, tool_name: str, params: dict, result: Any) -> None:
        self._state = EnvironmentState.READY

    async def on_dispose(self) -> None:
        self._state = EnvironmentState.DISPOSED


class RemoteVM(Environment):
    """Remote VM environment.

    Connects to a remote virtual machine via RDP, VNC, or SSH.
    """

    def __init__(self, host: str = "", port: int = 3389, protocol: str = "rdp") -> None:
        super().__init__()
        self._host = host
        self._port = port
        self._protocol = protocol

    async def initialize(self) -> EnvironmentInfo:
        self._state = EnvironmentState.INITIALIZING
        self._info = EnvironmentInfo(
            name=f"remote-{self._host}",
            type="remote",
            metadata={"host": self._host, "port": self._port, "protocol": self._protocol},
        )
        self._state = EnvironmentState.READY
        return self._info

    async def on_before_tool(self, tool_name: str, params: dict) -> dict:
        self._state = EnvironmentState.BUSY
        return params

    async def on_after_tool(self, tool_name: str, params: dict, result: Any) -> None:
        self._state = EnvironmentState.READY

    async def on_dispose(self) -> None:
        self._state = EnvironmentState.DISPOSED
