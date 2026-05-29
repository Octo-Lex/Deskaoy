"""Policy bridge — defer to AI-OS policy for GUI action preflight.

Before executing GUI actions, Deskaoy must be able to defer to
AI-OS policy for allow/deny/ask/dry-run-only/degraded decisions.

Hard rule: No GUI action should bypass AI-OS policy when running inside AI-OS.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Policy decision types
# ---------------------------------------------------------------------------

class PolicyEffect(StrEnum):
    """Possible outcomes of a policy preflight check."""
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
    ALLOW_DRY_RUN_ONLY = "allow_dry_run_only"
    ALLOW_WITH_OBLIGATIONS = "allow_with_obligations"
    DEGRADED = "degraded"


class Permission(StrEnum):
    """GUI action permissions that require policy preflight."""
    SCREEN_CAPTURE = "screen_capture"
    ACCESSIBILITY_READ = "accessibility_read"
    KEYBOARD_INPUT = "keyboard_input"
    MOUSE_INPUT = "mouse_input"
    WINDOW_FOCUS = "window_focus"
    CLIPBOARD_READ = "clipboard_read"
    CLIPBOARD_WRITE = "clipboard_write"
    BROWSER_NAVIGATION = "browser_navigation"
    NETWORK_ACCESS = "network_access"
    STEALTH_BROWSER = "stealth_browser"


@dataclass
class PolicyDecision:
    """Result of a policy preflight check."""
    effect: PolicyEffect
    reason: str = ""
    obligations: list[str] = field(default_factory=list)
    degraded_capabilities: list[str] = field(default_factory=list)
    policy_decision_id: str = ""


# ---------------------------------------------------------------------------
# Permission mapping — action → required permissions
# ---------------------------------------------------------------------------

ACTION_PERMISSIONS: dict[str, list[Permission]] = {
    "click":              [Permission.MOUSE_INPUT, Permission.WINDOW_FOCUS],
    "fill":               [Permission.KEYBOARD_INPUT, Permission.WINDOW_FOCUS],
    "type_text":          [Permission.KEYBOARD_INPUT],
    "key_press":          [Permission.KEYBOARD_INPUT],
    "scroll":             [Permission.MOUSE_INPUT],
    "screenshot":         [Permission.SCREEN_CAPTURE],
    "snapshot":           [Permission.ACCESSIBILITY_READ],
    "navigate":           [Permission.BROWSER_NAVIGATION, Permission.NETWORK_ACCESS],
    "hover":              [Permission.MOUSE_INPUT, Permission.WINDOW_FOCUS],
}


def permissions_for_action(action: str) -> list[Permission]:
    """Return the permissions required for a given action."""
    return ACTION_PERMISSIONS.get(action, [])


# ---------------------------------------------------------------------------
# Policy bridge
# ---------------------------------------------------------------------------

PolicyPreflightFn = Callable[[list[Permission], dict[str, Any]], Awaitable[PolicyDecision]]


class PolicyBridge:
    """Integration point for AI-OS policy preflight.

    When running inside AI-OS, the bridge delegates to the AI-OS policy
    service. When running standalone, all actions are allowed (dev mode).

    Action guard filtering (``enabled_actions`` / ``disabled_actions``)
    is inspired by gogcli's ``--enable-commands`` / ``--disable-commands``.
    """

    def __init__(
        self,
        *,
        preflight_fn: PolicyPreflightFn | None = None,
        dev_mode: bool = True,
        enabled_actions: set[str] | None = None,
        disabled_actions: set[str] | None = None,
    ) -> None:
        self._preflight_fn = preflight_fn
        self._dev_mode = dev_mode
        self._enabled_actions = enabled_actions  # None means all allowed
        self._disabled_actions = disabled_actions or set()

    # ── Action guard (gogcli pattern) ────────────

    def is_action_allowed(self, action: str) -> bool:
        """Check action against enabled/disabled guards.

        Dot-path prefix matching: if ``"gmail"`` is in ``disabled_actions``
        then both ``"gmail.send"`` and ``"gmail.search"`` are blocked.
        """
        # Disabled overrides everything
        for prefix in self._disabled_actions:
            if action == prefix or action.startswith(prefix + "."):
                return False

        # Enabled: if specified, only listed actions (and their prefixes) pass
        if self._enabled_actions is not None:
            for prefix in self._enabled_actions:
                if action == prefix or action.startswith(prefix + "."):
                    return True
            return False

        return True

    @property
    def is_connected(self) -> bool:
        """True when connected to AI-OS policy service."""
        return self._preflight_fn is not None

    async def preflight(
        self,
        action: str,
        context: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        """Check policy for a GUI action.

        Returns the policy decision. In dev mode, always allows.
        When connected to AI-OS, delegates to the policy service.

        Action guards are checked **before** permission preflight.
        """
        # Action guard filtering (gogcli pattern)
        if not self.is_action_allowed(action):
            return PolicyDecision(
                effect=PolicyEffect.DENY,
                reason=f"Action '{action}' blocked by action guard (enabled/disabled list)",
            )

        perms = permissions_for_action(action)

        # Dev mode: allow everything
        if self._dev_mode and not self.is_connected:
            return PolicyDecision(
                effect=PolicyEffect.ALLOW,
                reason="dev mode: no policy service connected",
            )

        # No permissions needed
        if not perms:
            return PolicyDecision(
                effect=PolicyEffect.ALLOW,
                reason="no permissions required",
            )

        # Delegate to AI-OS policy
        if self._preflight_fn is not None:
            try:
                return await self._preflight_fn(perms, context or {})
            except Exception as exc:
                logger.warning("Policy preflight failed: %s — defaulting to deny", exc)
                return PolicyDecision(
                    effect=PolicyEffect.DENY,
                    reason=f"Policy service error: {exc}",
                )

        # Fallback: allow in dev mode, deny otherwise
        if self._dev_mode:
            return PolicyDecision(
                effect=PolicyEffect.ALLOW,
                reason="dev mode fallback",
            )

        return PolicyDecision(
            effect=PolicyEffect.DENY,
            reason="No policy service configured and not in dev mode",
        )

    async def check_stealth_policy(self) -> PolicyDecision:
        """Check whether stealth browser automation is allowed.

        Stealth is disabled by default and requires explicit policy allow.
        """
        if self._preflight_fn is not None:
            return await self._preflight_fn([Permission.STEALTH_BROWSER], {})
        return PolicyDecision(
            effect=PolicyEffect.DENY,
            reason="Stealth browser automation is disabled by default",
        )
