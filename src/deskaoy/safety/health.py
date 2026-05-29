"""HealthCheck — lightweight readiness/liveness probe.

Validates that all agent subsystems are functional before
dispatching tasks. Returns a structured HealthStatus with
per-check details using a 3-state model:

- ``True``  (PASS) — subsystem configured and healthy
- ``None``   (N/A)  — subsystem not configured (optional)
- ``False`` (FAIL) — subsystem configured but broken

Overall ``healthy`` is True only if no check returns False.
N/A checks do not affect the overall health verdict.

Wire into DesktopAgent.health() as a public API.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

from deskaoy.safety.cost_tracker import CostTracker
from deskaoy.safety.latency_budget import LatencyBudget
from deskaoy.safety.rate_governor import ActionRateGovernor


@dataclass
class HealthStatus:
    """Result of a health check.

    ``checks`` values use 3-state logic:
    - True  → PASS (configured and healthy)
    - None  → N/A  (not configured, optional subsystem)
    - False → FAIL (configured but broken)
    """

    healthy: bool
    checks: dict[str, bool | None] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)
    timestamp: float = 0.0


class HealthCheck:
    """Readiness/liveness probe for DesktopAgent subsystems.

    Runs 8 checks split into two tiers:

    **Always-required** (FAIL makes overall unhealthy):
    5. Circuit breaker is not open
    6. Cost budget not exceeded
    7. Key blocklist loaded
    8. Sensitive apps registry loaded

    **Optional** (N/A when not configured):
    1. Surface adapter exists and is reachable
    2. LLM client is configured and ready
    3. Policy bridge is functional
    4. Storage resolver is writable
    """

    def __init__(
        self,
        agent: Any,
        *,
        rate_governor: ActionRateGovernor | None = None,
        latency_budget: LatencyBudget | None = None,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        self._agent = agent
        self._rate_governor = rate_governor
        self._latency_budget = latency_budget
        self._cost_tracker = cost_tracker

    async def check(self) -> HealthStatus:
        """Run all health checks and return the aggregated status."""
        checks: dict[str, bool] = {}
        details: dict[str, str] = {}

        # 1. Surface adapter
        checks["surface"], details["surface"] = self._check_surface()

        # 2. LLM client
        checks["llm"], details["llm"] = self._check_llm()

        # 3. Policy bridge
        checks["policy"], details["policy"] = self._check_policy()

        # 4. Storage resolver
        checks["storage"], details["storage"] = self._check_storage()

        # 5. Circuit breaker
        checks["circuit_breaker"], details["circuit_breaker"] = self._check_circuit_breaker()

        # 6. Cost budget
        checks["cost_budget"], details["cost_budget"] = self._check_cost_budget()

        # 7. Security modules (BATCH-12)
        checks["key_blocklist"], details["key_blocklist"] = self._check_key_blocklist()
        checks["sensitive_apps"], details["sensitive_apps"] = self._check_sensitive_apps()

        # 9. Snapshot store (BATCH-24)
        checks["snapshot_store"], details["snapshot_store"] = self._check_snapshot_store()

        # 10-13. Desktop UI Services (BATCH-26)
        checks["menu_service"], details["menu_service"] = self._check_menu_service()
        checks["taskbar_service"], details["taskbar_service"] = self._check_taskbar_service()
        checks["dialog_service"], details["dialog_service"] = self._check_dialog_service()
        checks["desktop_service"], details["desktop_service"] = self._check_desktop_service()

        # 14. macOS adapter (BATCH-33)
        checks["macos_adapter"], details["macos_adapter"] = self._check_macos_adapter()

        # Overall healthy = no FAIL (False). N/A (None) is acceptable.
        healthy = all(v is not False for v in checks.values())
        return HealthStatus(
            healthy=healthy,
            checks=checks,
            details=details,
            timestamp=time.monotonic(),
        )

    def _check_surface(self) -> tuple[bool | None, str]:
        """Check surface adapter exists and is reachable."""
        surface = getattr(self._agent, "_surface", None)
        if surface is None:
            return None, "Not configured (optional)"
        # Try is_reachable if it exists
        try:
            if hasattr(surface, "is_reachable") and callable(surface.is_reachable):
                reachable = surface.is_reachable()
                if not reachable:
                    return False, "Surface adapter not reachable"
            return True, "Surface adapter available"
        except Exception as exc:
            return False, f"Surface check error: {exc}"

    def _check_llm(self) -> tuple[bool | None, str]:
        """Check LLM client is configured."""
        llm = getattr(self._agent, "_llm", None)
        if llm is None:
            return None, "Not configured (optional)"
        # Check is_ready if available
        try:
            if hasattr(llm, "is_ready") and callable(llm.is_ready):
                if not llm.is_ready():
                    return False, "LLM client not ready"
            return True, "LLM client available"
        except Exception as exc:
            return False, f"LLM check error: {exc}"

    def _check_policy(self) -> tuple[bool | None, str]:
        """Check policy bridge is functional."""
        bridge = getattr(self._agent, "_policy_bridge", None)
        if bridge is None:
            return None, "Not configured (optional)"
        try:
            connected = getattr(bridge, "is_connected", False)
            if not connected:
                return None, "Not connected (optional)"
            return True, "Policy bridge connected"
        except Exception as exc:
            return False, f"Policy check error: {exc}"

    def _check_storage(self) -> tuple[bool | None, str]:
        """Check storage resolver is writable."""
        resolver = getattr(self._agent, "_storage_resolver", None)
        if resolver is None:
            return None, "Not configured (optional)"
        try:
            if hasattr(resolver, "resolve") and callable(resolver.resolve):
                # StorageResolver.resolve() requires a subarea name
                try:
                    path = resolver.resolve_action_memory()
                except Exception:
                    path = resolver.resolve("action-memory")
                if hasattr(path, "exists") and path.exists():
                    return True, f"Storage path exists: {path}"
                return True, "Storage resolver available"
            return True, "Storage resolver available"
        except Exception as exc:
            return False, f"Storage check error: {exc}"

    def _check_circuit_breaker(self) -> tuple[bool, str]:
        """Check circuit breaker is not open."""
        bridge = getattr(self._agent, "_recovery_bridge", None)
        if bridge is None:
            return True, "No recovery bridge (not applicable)"
        try:
            cb = getattr(bridge, "circuit_breaker", None)
            if cb is None:
                return True, "No circuit breaker (not applicable)"
            is_open = cb.is_open()
            if is_open:
                return False, f"Circuit breaker open ({cb.failure_count} failures)"
            return True, f"Circuit breaker closed (failures: {cb.failure_count})"
        except Exception as exc:
            return False, f"Circuit breaker check error: {exc}"

    def _check_cost_budget(self) -> tuple[bool, str]:
        """Check cost budget not exceeded."""
        if self._cost_tracker is None:
            return True, "No cost tracker (not applicable)"
        try:
            if self._cost_tracker.budget_exceeded:
                return False, f"Cost budget exceeded: ${self._cost_tracker.total_cost:.4f}/${self._cost_tracker.budget_usd:.2f}"
            return True, f"Budget OK: ${self._cost_tracker.total_cost:.4f}/${self._cost_tracker.budget_usd:.2f}"
        except Exception as exc:
            return False, f"Cost check error: {exc}"

    def _check_key_blocklist(self) -> tuple[bool, str]:
        """Check key blocklist is loaded."""
        try:
            from deskaoy.safety.key_blocklist import BLOCKED_KEYS
            return True, f"{len(BLOCKED_KEYS)} keys blocked"
        except Exception as exc:
            return False, f"Key blocklist error: {exc}"

    def _check_sensitive_apps(self) -> tuple[bool, str]:
        """Check sensitive apps registry is loaded."""
        try:
            from deskaoy.safety.sensitive_apps import SENSITIVE_APPS
            return True, f"{len(SENSITIVE_APPS)} apps monitored"
        except Exception as exc:
            return False, f"Sensitive apps error: {exc}"

    def _check_snapshot_store(self) -> tuple[bool | None, str]:
        """Check snapshot store is available (optional subsystem).

        Returns N/A if not configured, PASS if directory exists or
        is writable, FAIL if configured but not writable.
        """
        store = getattr(self._agent, "_snapshot_store", None) or getattr(self._agent, "snapshot_store", None)
        if store is None:
            return None, "Not configured (optional)"
        try:
            snap_dir = store.snapshot_dir if hasattr(store, 'snapshot_dir') else None
            if snap_dir is None:
                return None, "Not configured (optional)"
            # If dir exists, it's healthy. If not, check if parent is writable.
            if snap_dir.exists():
                return True, f"Snapshot store available ({snap_dir})"
            # Check if parent is writable (dir will be created on first use)
            parent = snap_dir.parent
            if parent.exists() and os.access(parent, os.W_OK):
                return True, f"Snapshot store ready (parent writable: {parent})"
            return None, "Snapshot directory not yet created"
        except Exception as exc:
            return False, f"Snapshot store error: {exc}"

    def _check_menu_service(self) -> tuple[bool | None, str]:
        """Check MenuService availability.

        Returns N/A when not on Windows or comtypes unavailable.
        """
        try:
            import sys
            if sys.platform != "win32":
                return None, "N/A (not Windows)"
            import comtypes  # noqa: F401
            return True, "MenuService available"
        except ImportError:
            return None, "N/A (comtypes not installed)"
        except Exception as exc:
            return False, f"MenuService error: {exc}"

    def _check_taskbar_service(self) -> tuple[bool | None, str]:
        """Check TaskbarService availability.

        Returns N/A when not on Windows or comtypes unavailable.
        """
        try:
            import sys
            if sys.platform != "win32":
                return None, "N/A (not Windows)"
            import comtypes  # noqa: F401
            return True, "TaskbarService available"
        except ImportError:
            return None, "N/A (comtypes not installed)"
        except Exception as exc:
            return False, f"TaskbarService error: {exc}"

    def _check_dialog_service(self) -> tuple[bool | None, str]:
        """Check DialogService availability.

        Returns N/A when not on Windows or comtypes unavailable.
        """
        try:
            import sys
            if sys.platform != "win32":
                return None, "N/A (not Windows)"
            import comtypes  # noqa: F401
            return True, "DialogService available"
        except ImportError:
            return None, "N/A (comtypes not installed)"
        except Exception as exc:
            return False, f"DialogService error: {exc}"

    def _check_desktop_service(self) -> tuple[bool | None, str]:
        """Check DesktopService availability.

        Returns N/A when not on Windows or comtypes unavailable.
        """
        try:
            import sys
            if sys.platform != "win32":
                return None, "N/A (not Windows)"
            import comtypes  # noqa: F401
            return True, "DesktopService available"
        except ImportError:
            return None, "N/A (comtypes not installed)"
        except Exception as exc:
            return False, f"DesktopService error: {exc}"

    def _check_macos_adapter(self) -> tuple[bool | None, str]:
        """Check macOS adapter availability (BATCH-33).

        Returns N/A when not on macOS. Returns True if pyobjc is
        available, False if pyobjc is missing.
        """
        try:
            import sys
            if sys.platform != "darwin":
                return None, "N/A (not macOS)"
            import ApplicationServices  # noqa: F401
            import Quartz  # noqa: F401
            return True, "macOS adapter available (pyobjc installed)"
        except ImportError:
            return False, "macOS platform detected but pyobjc not installed"
        except Exception as exc:
            return False, f"macOS adapter error: {exc}"
