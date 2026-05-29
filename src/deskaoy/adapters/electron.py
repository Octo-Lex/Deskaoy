"""Electron app CDP registry — fast control of Chromium-based desktop apps.

Electron apps expose Chrome DevTools Protocol when launched with
``--remote-debugging-port=N``.  This module maintains a registry of known
Electron apps and their assigned CDP ports, so the DesktopAgent can
connect via CDP (browser-like selectors) instead of slow UIA tree walking.

Adapted from OpenCLI's ``electron-apps.ts``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ElectronAppEntry:
    """Metadata for a known Electron desktop app."""
    name: str
    process_name: str           # "Cursor", "Notion", "Code"
    cdp_port: int               # unique per app
    executable_names: list[str] = field(default_factory=list)
    bundle_id: str | None = None     # macOS only
    extra_args: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Built-in registry
# ---------------------------------------------------------------------------

ELECTRON_APPS: dict[str, ElectronAppEntry] = {
    "cursor": ElectronAppEntry(
        name="Cursor",
        process_name="Cursor",
        cdp_port=9226,
        executable_names=["Cursor.exe", "cursor"],
    ),
    "notion": ElectronAppEntry(
        name="Notion",
        process_name="Notion",
        cdp_port=9230,
        executable_names=["Notion.exe", "notion"],
    ),
    "discord": ElectronAppEntry(
        name="Discord",
        process_name="Discord",
        cdp_port=9232,
        executable_names=["Discord.exe", "discord"],
    ),
    "vscode": ElectronAppEntry(
        name="VS Code",
        process_name="Code",
        cdp_port=9224,
        executable_names=["Code.exe", "code"],
    ),
    "chatgpt": ElectronAppEntry(
        name="ChatGPT",
        process_name="ChatGPT",
        cdp_port=9236,
        executable_names=["ChatGPT.exe", "chatgpt"],
    ),
}


class ElectronLauncher:
    """Detect, launch, and connect to Electron apps via CDP."""

    def __init__(self, apps: dict[str, ElectronAppEntry] | None = None) -> None:
        self._apps = apps or ELECTRON_APPS

    def get_entry(self, app_name: str) -> ElectronAppEntry | None:
        """Look up an app by name (case-insensitive)."""
        return self._apps.get(app_name.lower())

    def get_cdp_url(self, app_name: str) -> str:
        """Return the CDP WebSocket URL for an app."""
        entry = self.get_entry(app_name)
        if entry is None:
            raise ValueError(f"Unknown Electron app: {app_name}")
        return f"http://localhost:{entry.cdp_port}"

    def is_running(self, app_name: str) -> bool:
        """Check if an Electron app is currently running."""
        entry = self.get_entry(app_name)
        if entry is None:
            return False
        try:
            import psutil
            for proc in psutil.process_iter(["name"]):
                if proc.info.get("name", "").lower() == entry.process_name.lower():
                    return True
        except ImportError:
            pass
        return False

    @property
    def registered_apps(self) -> list[str]:
        return list(self._apps.keys())
