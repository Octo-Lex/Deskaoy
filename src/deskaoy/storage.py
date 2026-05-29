"""AIOS_HOME storage resolver — production vs development storage paths.

Production durable state is stored under AIOS_HOME.
Standalone development uses a local fallback with an explicit dev mode flag.

Hard rule: No production durable state outside AIOS_HOME.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAPABILITY_ID = "aios.first_party.deskaoy"
AIOS_HOME_ENV = "AIOS_HOME"
DEV_MODE_ENV = "DESKTOP_AGENT_DEV"

# Production subareas
SUBAREAS = [
    "action-memory",
    "checkpoints",
    "artifacts",
    "logs",
    "temp",
]


# ---------------------------------------------------------------------------
# Storage resolver
# ---------------------------------------------------------------------------

class StorageResolver:
    """Resolve storage paths under AIOS_HOME or development fallback.

    Usage::

        storage = StorageResolver()
        mem_dir = storage.resolve("action-memory")
        # → AIOS_HOME/capabilities/aios.first_party.deskaoy/action-memory/
        # or ~/.deskaoy-dev/action-memory/ in dev mode
    """

    def __init__(
        self,
        *,
        aios_home: Path | None = None,
        dev_mode: bool | None = None,
    ) -> None:
        self._aios_home = Path(aios_home) if aios_home is not None else None
        self._dev_mode = dev_mode

    @property
    def is_dev_mode(self) -> bool:
        """True when running in standalone development mode."""
        if self._dev_mode is not None:
            return self._dev_mode
        return os.environ.get(DEV_MODE_ENV, "").lower() in ("1", "true", "yes")

    @property
    def aios_home(self) -> Path | None:
        """AIOS_HOME root, if configured."""
        if self._aios_home is not None:
            return self._aios_home
        env_val = os.environ.get(AIOS_HOME_ENV)
        if env_val:
            return Path(env_val)
        return None

    @property
    def capability_root(self) -> Path:
        """Root directory for this capability's durable state."""
        if self.is_dev_mode or self.aios_home is None:
            return Path.home() / ".deskaoy-dev"
        return self.aios_home / "capabilities" / CAPABILITY_ID

    def resolve(self, subarea: str) -> Path:
        """Resolve a storage subarea to an absolute path.

        Creates the directory if it doesn't exist.
        """
        if subarea not in SUBAREAS:
            raise ValueError(f"Unknown subarea: {subarea}. Valid: {SUBAREAS}")
        path = self.capability_root / subarea
        path.mkdir(parents=True, exist_ok=True)
        return path

    def resolve_action_memory(self) -> Path:
        return self.resolve("action-memory")

    def resolve_checkpoints(self) -> Path:
        return self.resolve("checkpoints")

    def resolve_artifacts(self) -> Path:
        return self.resolve("artifacts")

    def resolve_logs(self) -> Path:
        return self.resolve("logs")

    def resolve_temp(self) -> Path:
        return self.resolve("temp")

    @property
    def storage_mode(self) -> str:
        """Human-readable storage mode description."""
        if self.is_dev_mode:
            return "development"
        if self.aios_home:
            return "production"
        return "development (no AIOS_HOME)"
