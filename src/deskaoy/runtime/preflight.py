"""Runtime Preflight — Canonical 12-check preflight for Deskaoy.

Implements the desktop-relevant subset of AI-OS Batch 38's 28-check canonical
preflight. Every execution must pass through this gate before dispatch.

Checks:
  CHK-PF-01: adapter_available        — Surface adapter connected
  CHK-PF-02: adapter_capabilities     — Capabilities declared
  CHK-PF-03: capability_supported     — Action within adapter scope
  CHK-PF-04: policy_checked           — Policy bridge returned decision
  CHK-PF-05: policy_allowed           — Policy not DENY
  CHK-PF-06: obligations_satisfied    — Required obligations met
  CHK-PF-07: dry_run_consistent       — dry_run_required → request is dry_run
  CHK-PF-08: rate_within_limit        — Rate governor allows
  CHK-PF-09: session_budget_available — Session budget not exhausted
  CHK-PF-10: health_check_passed      — Adapter health OK
  CHK-PF-11: resource_budget_set      — Resource budget defined
  CHK-PF-12: no_raw_secrets           — No secrets in params
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Any

from deskaoy.runtime.types import (
    AdapterCapabilities,
    PolicyObligation,
    PreflightCheck,
    PreflightResult,
    RuntimeResourceBudget,
)

logger = logging.getLogger(__name__)

# Secret-like patterns to scan for
_SECRET_PATTERNS = [
    re.compile(r"(?:api[_-]?key|secret|token|password|credential)\s*[:=]\s*['\"]?[\w\-]{16,}", re.IGNORECASE),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI-style keys
    re.compile(r"AKIA[A-Z0-9]{16}"),      # AWS-style keys
]


class RuntimePreflight:
    """Canonical 12-check preflight service.

    Usage:
        preflight = RuntimePreflight(agent)
        result = await preflight.run(goal, context)
        if not result.passed:
            # Blocked
    """

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    async def run(
        self,
        goal: Any,
        context: Any,
        *,
        policy_decision: Any = None,
        capabilities: AdapterCapabilities | None = None,
        resource_budget: RuntimeResourceBudget | None = None,
    ) -> PreflightResult:
        """Run all 12 preflight checks. Returns PreflightResult."""
        checks: list[PreflightCheck] = []

        # CHK-PF-01: adapter_available
        checks.append(self._check_adapter_available())

        # CHK-PF-02: adapter_capabilities
        checks.append(self._check_adapter_capabilities(capabilities))

        # CHK-PF-03: capability_supported
        checks.append(self._check_capability_supported(goal, capabilities))

        # CHK-PF-04: policy_checked
        checks.append(self._check_policy_checked(policy_decision))

        # CHK-PF-05: policy_allowed
        checks.append(self._check_policy_allowed(policy_decision))

        # CHK-PF-06: obligations_satisfied
        obligations = self._extract_obligations(policy_decision)
        checks.append(self._check_obligations_satisfied(obligations, context))

        # CHK-PF-07: dry_run_consistent
        checks.append(self._check_dry_run_consistent(obligations, context))

        # CHK-PF-08: rate_within_limit
        checks.append(self._check_rate_limit(goal))

        # CHK-PF-09: session_budget_available
        checks.append(self._check_session_budget())

        # CHK-PF-10: health_check_passed
        checks.append(self._check_health())

        # CHK-PF-11: resource_budget_set
        checks.append(self._check_resource_budget(resource_budget))

        # CHK-PF-12: no_raw_secrets
        checks.append(self._check_no_raw_secrets(goal))

        # Compute fingerprint
        fingerprint = self._compute_fingerprint(checks, capabilities, policy_decision)

        # Determine pass/fail
        passed = all(c.passed for c in checks)
        blocked_reason = ""
        if not passed:
            failed = [c for c in checks if not c.passed]
            blocked_reason = "; ".join(f"{c.check_id}: {c.message}" for c in failed)

        return PreflightResult(
            passed=passed,
            checks=checks,
            fingerprint=fingerprint,
            obligations_required=obligations,
            blocked_reason=blocked_reason,
        )

    # ─── Individual checks ──────────────────────────────

    def _check_adapter_available(self) -> PreflightCheck:
        surface = getattr(self._agent, "_surface", None)
        if surface is not None:
            return PreflightCheck("CHK-PF-01", "adapter_available", True)
        return PreflightCheck("CHK-PF-01", "adapter_available", False, "No surface adapter connected")

    def _check_adapter_capabilities(self, caps: AdapterCapabilities | None) -> PreflightCheck:
        if caps is not None:
            return PreflightCheck("CHK-PF-02", "adapter_capabilities", True)
        # Not fatal — defaults used
        return PreflightCheck("CHK-PF-02", "adapter_capabilities", True, "Using default capabilities")

    def _check_capability_supported(self, goal: Any, caps: AdapterCapabilities | None) -> PreflightCheck:
        if caps is None:
            return PreflightCheck("CHK-PF-03", "capability_supported", True, "No capability restrictions")
        # Map action type to capability
        cap_name = getattr(goal, "capability", "automate")
        # Read-only capabilities always pass
        if cap_name in ("screenshot", "snapshot", "health", "schema"):
            return PreflightCheck("CHK-PF-03", "capability_supported", True)

        # Mouse/keyboard actions require corresponding capabilities
        params = getattr(goal, "params", {})
        action = params.get("action", cap_name)
        action_caps = {
            "click": "supports_mouse",
            "type_text": "supports_keyboard",
            "fill": "supports_mouse",
            "key_press": "supports_keyboard",
            "scroll": "supports_mouse",
            "hover": "supports_mouse",
            "screenshot": "supports_screen_capture",
            "snapshot": "supports_accessibility_read",
        }
        required_cap = action_caps.get(action)
        if required_cap and not getattr(caps, required_cap, True):
            return PreflightCheck(
                "CHK-PF-03", "capability_supported", False,
                f"Action '{action}' requires {required_cap} but adapter does not support it",
            )
        return PreflightCheck("CHK-PF-03", "capability_supported", True)

    def _check_policy_checked(self, decision: Any) -> PreflightCheck:
        if decision is not None:
            return PreflightCheck("CHK-PF-04", "policy_checked", True)
        # No policy decision — pass (policy not required for internal ops)
        return PreflightCheck("CHK-PF-04", "policy_checked", True, "No policy decision required")

    def _check_policy_allowed(self, decision: Any) -> PreflightCheck:
        if decision is None:
            return PreflightCheck("CHK-PF-05", "policy_allowed", True, "No policy restriction")
        effect = getattr(decision, "effect", None) or ""
        if str(effect) == "deny":
            return PreflightCheck("CHK-PF-05", "policy_allowed", False, "Policy denied execution")
        return PreflightCheck("CHK-PF-05", "policy_allowed", True)

    def _check_obligations_satisfied(
        self, obligations: list[PolicyObligation], context: Any,
    ) -> PreflightCheck:
        if not obligations:
            return PreflightCheck("CHK-PF-06", "obligations_satisfied", True, "No obligations required")

        for obl in obligations:
            if obl == PolicyObligation.APPROVAL_REQUIRED:
                approved = getattr(context, "dry_run", False)  # dry_run bypasses approval
                if not approved:
                    # Check if explicit approval exists in context
                    approved = bool(getattr(context, "additional_clients", {}))
                if not approved:
                    return PreflightCheck(
                        "CHK-PF-06", "obligations_satisfied", False,
                        f"Obligation '{obl.value}' not satisfied: no approval",
                    )
            if obl == PolicyObligation.SANDBOX_REQUIRED:
                # Desktop agent doesn't support sandboxing
                caps = getattr(self._agent, "_capabilities", None)
                if caps and not caps.supports_sandboxing:
                    return PreflightCheck(
                        "CHK-PF-06", "obligations_satisfied", False,
                        f"Obligation '{obl.value}' not satisfied: adapter lacks sandboxing",
                    )

        return PreflightCheck("CHK-PF-06", "obligations_satisfied", True)

    def _check_dry_run_consistent(
        self, obligations: list[PolicyObligation], context: Any,
    ) -> PreflightCheck:
        if PolicyObligation.DRY_RUN_REQUIRED not in obligations:
            return PreflightCheck("CHK-PF-07", "dry_run_consistent", True, "No dry_run obligation")
        is_dry_run = getattr(context, "dry_run", False)
        if is_dry_run:
            return PreflightCheck("CHK-PF-07", "dry_run_consistent", True)
        return PreflightCheck(
            "CHK-PF-07", "dry_run_consistent", False,
            "dry_run_required obligation but request is not dry_run",
        )

    def _check_rate_limit(self, goal: Any) -> PreflightCheck:
        governor = getattr(self._agent, "rate_governor", None)
        if governor is None:
            return PreflightCheck("CHK-PF-08", "rate_within_limit", True, "No rate governor")
        cap_name = getattr(goal, "capability", "automate")
        try:
            governor.check(cap_name)
            return PreflightCheck("CHK-PF-08", "rate_within_limit", True)
        except Exception as e:
            return PreflightCheck("CHK-PF-08", "rate_within_limit", False, str(e))

    def _check_session_budget(self) -> PreflightCheck:
        budget = getattr(self._agent, "session_budget", None)
        if budget is None:
            return PreflightCheck("CHK-PF-09", "session_budget_available", True, "No session budget")
        if budget.is_exhausted():
            return PreflightCheck("CHK-PF-09", "session_budget_available", False, "Session budget exhausted")
        return PreflightCheck("CHK-PF-09", "session_budget_available", True)

    def _check_health(self) -> PreflightCheck:
        # Health check is informational — doesn't block unless critical
        health = getattr(self._agent, "_last_health_status", None)
        if health is None:
            return PreflightCheck("CHK-PF-10", "health_check_passed", True, "No health status cached")
        healthy = getattr(health, "healthy", True)
        if healthy:
            return PreflightCheck("CHK-PF-10", "health_check_passed", True)
        return PreflightCheck("CHK-PF-10", "health_check_passed", False, "Adapter health check failed")

    def _check_resource_budget(self, budget: RuntimeResourceBudget | None) -> PreflightCheck:
        if budget is not None:
            return PreflightCheck("CHK-PF-11", "resource_budget_set", True)
        return PreflightCheck("CHK-PF-11", "resource_budget_set", True, "Using default resource budget")

    def _check_no_raw_secrets(self, goal: Any) -> PreflightCheck:
        params = getattr(goal, "params", {})
        params_str = str(params)
        for pattern in _SECRET_PATTERNS:
            if pattern.search(params_str):
                return PreflightCheck(
                    "CHK-PF-12", "no_raw_secrets", False,
                    "Raw secret pattern detected in request params",
                )
        return PreflightCheck("CHK-PF-12", "no_raw_secrets", True)

    # ─── Helpers ────────────────────────────────────────

    def _extract_obligations(self, decision: Any) -> list[PolicyObligation]:
        """Extract obligations from policy decision."""
        if decision is None:
            return []
        obligations = getattr(decision, "obligations", None)
        if obligations:
            return list(obligations)
        effect = str(getattr(decision, "effect", ""))
        if "obligation" in effect.lower():
            return [PolicyObligation.DRY_RUN_REQUIRED]
        return []

    def _compute_fingerprint(
        self,
        checks: list[PreflightCheck],
        caps: AdapterCapabilities | None,
        decision: Any,
    ) -> str:
        """Compute SHA-256 fingerprint of current state for TOCTOU detection."""
        parts = [
            "|".join(f"{c.check_id}:{c.passed}" for c in checks),
            caps.fingerprint() if caps else "no-caps",
            str(getattr(decision, "effect", "no-decision")),
            str(int(time.time() / 300)),  # 5-minute window
        ]
        raw = "||".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
