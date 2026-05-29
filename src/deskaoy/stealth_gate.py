"""Stealth policy gate — stealth browser automation is disabled by default.

Stealth behavior requires:
  - Explicit policy allow
  - User-facing disclosure
  - Higher risk classification
  - Receipt/evidence
  - Disabled-by-default distribution decision

Hard rule: No silent stealth capability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stealth risk classification
# ---------------------------------------------------------------------------

class StealthRiskLevel(StrEnum):
    NONE = "none"               # No stealth — normal browser automation
    LOW = "low"                 # TLS fingerprint mimicry only
    MEDIUM = "medium"           # Browser fingerprint spoofing
    HIGH = "high"               # Anti-detection evasion (CAPTCHA bypass, etc.)


@dataclass
class StealthPolicyDecision:
    """Decision on whether stealth features are allowed."""
    allowed: bool
    risk_level: StealthRiskLevel = StealthRiskLevel.NONE
    reason: str = ""
    requires_disclosure: bool = False
    requires_receipt: bool = False
    policy_decision_id: str = ""


# ---------------------------------------------------------------------------
# Stealth gate
# ---------------------------------------------------------------------------

class StealthGate:
    """Gate that controls whether stealth features can be activated.

    Stealth is DISABLED by default. Must be explicitly enabled by:
    1. AI-OS policy allow via policy bridge, OR
    2. Explicit user consent in development mode

    This gate wraps the StealthManager and prevents initialization
    when policy does not allow it.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        policy_bridge: Any = None,
    ) -> None:
        self._enabled = enabled
        self._policy_bridge = policy_bridge

    @property
    def is_enabled(self) -> bool:
        """Whether stealth features are currently enabled."""
        return self._enabled

    async def check_policy(self) -> StealthPolicyDecision:
        """Check whether stealth is allowed via policy bridge."""
        if self._policy_bridge is not None:
            from deskaoy.policy import PolicyBridge, PolicyEffect
            if isinstance(self._policy_bridge, PolicyBridge):
                decision = await self._policy_bridge.check_stealth_policy()
                if decision.effect == PolicyEffect.ALLOW:
                    return StealthPolicyDecision(
                        allowed=True,
                        risk_level=StealthRiskLevel.HIGH,
                        reason="Policy allows stealth",
                        requires_disclosure=True,
                        requires_receipt=True,
                        policy_decision_id=decision.policy_decision_id,
                    )

        if self._enabled:
            return StealthPolicyDecision(
                allowed=True,
                risk_level=StealthRiskLevel.HIGH,
                reason="Development mode: stealth explicitly enabled",
                requires_disclosure=True,
            )

        return StealthPolicyDecision(
            allowed=False,
            reason="Stealth browser automation is disabled by default. "
                   "Enable via AI-OS policy or DESKTOP_AGENT_STEALTH=1.",
        )

    def enable(self, *, reason: str = "") -> None:
        """Explicitly enable stealth (development mode only)."""
        self._enabled = True
        logger.warning(
            "Stealth enabled: %s. This requires user-facing disclosure.",
            reason or "manual override",
        )

    def disable(self) -> None:
        """Disable stealth features."""
        self._enabled = False


# ---------------------------------------------------------------------------
# Default gate — stealth disabled
# ---------------------------------------------------------------------------

# Module-level default: stealth is OFF
default_stealth_gate = StealthGate(enabled=False)
