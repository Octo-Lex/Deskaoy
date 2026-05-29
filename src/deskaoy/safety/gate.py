"""SafetyGate — tier-based action evaluation for Deskaoy.

Ported from SUPER-BROWSER security/gate.py pattern.

Every action passes through evaluate() before executing.
Returns a SafetyDecision — pure function, no side effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class ActionTier(StrEnum):
    """Action risk tier — used for permission escalation."""
    READ = "read"
    INPUT = "input"
    DESTRUCTIVE = "destructive"
    SYSTEM = "system"


@dataclass(frozen=True)
class SafetyDecision:
    """Result of safety gate evaluation."""
    tier: ActionTier
    allowed: bool
    requires_confirm: bool = False
    reason: str | None = None


# Tool name → default tier
_TOOL_TIERS: dict[str, ActionTier] = {
    # Read operations — always safe
    "observe": ActionTier.READ,
    "snapshot": ActionTier.READ,
    "screenshot": ActionTier.READ,
    "list_windows": ActionTier.READ,
    "get_element": ActionTier.READ,
    "get_text": ActionTier.READ,
    "health_check": ActionTier.READ,
    "doctor": ActionTier.READ,
    # Input operations — generally safe
    "click": ActionTier.INPUT,
    "type_text": ActionTier.INPUT,
    "press_key": ActionTier.INPUT,
    "scroll": ActionTier.INPUT,
    "hover": ActionTier.INPUT,
    "drag": ActionTier.INPUT,
    "navigate": ActionTier.INPUT,
    "fill": ActionTier.INPUT,
    "start_app": ActionTier.INPUT,
    "switch_window": ActionTier.INPUT,
    # Destructive operations — require confirmation
    "close_window": ActionTier.DESTRUCTIVE,
    "kill_process": ActionTier.DESTRUCTIVE,
    "delete_file": ActionTier.DESTRUCTIVE,
    "move_file": ActionTier.DESTRUCTIVE,
    "rename_file": ActionTier.DESTRUCTIVE,
    # System operations — require confirmation
    "execute_shell": ActionTier.SYSTEM,
    "run_command": ActionTier.SYSTEM,
    "registry_edit": ActionTier.SYSTEM,
    "install_software": ActionTier.SYSTEM,
}

# Target labels that escalate INPUT → requires_confirm
_CONFIRM_LABEL_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bsend\b", re.I),
    re.compile(r"\bdelete\b", re.I),
    re.compile(r"\bremove\b", re.I),
    re.compile(r"\bpurchase\b", re.I),
    re.compile(r"\btransfer\b", re.I),
    re.compile(r"\blog\s*out\b", re.I),
    re.compile(r"\bsign\s*out\b", re.I),
    re.compile(r"\bcheckout\b", re.I),
    re.compile(r"\bformat\b", re.I),
    re.compile(r"\bshutdown\b", re.I),
    re.compile(r"\brestart\b", re.I),
]

# Sensitive app patterns — always escalate
_SENSITIVE_APP_PATTERNS: list[re.Pattern] = [
    re.compile(r"banking", re.I),
    re.compile(r"crypto", re.I),
    re.compile(r"wallet", re.I),
    re.compile(r"password", re.I),
    re.compile(r"1password", re.I),
    re.compile(r"bitwarden", re.I),
    re.compile(r"keepass", re.I),
    re.compile(r"lastpass", re.I),
]


def evaluate(
    tool: str,
    args: dict | None = None,
    target_label: str | None = None,
    app_name: str | None = None,
    allowed_tiers: set[ActionTier] | None = None,
) -> SafetyDecision:
    """Evaluate whether an action should proceed.

    Pure function — no side effects.

    Parameters
    ----------
    tool:
        Action/tool name (e.g. "click", "observe", "execute_shell").
    args:
        Tool arguments (reserved for future analysis).
    target_label:
        Optional OCR/a11y label of the target element.
    app_name:
        Optional name of the target application.
    allowed_tiers:
        Set of tiers the current session permits. If None, all tiers allowed.

    Returns
    -------
    SafetyDecision with tier, allowed flag, and optional reason.
    """
    tier = _TOOL_TIERS.get(tool, ActionTier.INPUT)

    # Check if tier is permitted at all
    if allowed_tiers is not None and tier not in allowed_tiers:
        return SafetyDecision(
            tier=tier,
            allowed=False,
            reason=f"Action tier '{tier.value}' not permitted in current session",
        )

    # Destructive and System tiers always require confirmation
    if tier in (ActionTier.DESTRUCTIVE, ActionTier.SYSTEM):
        return SafetyDecision(
            tier=tier,
            allowed=True,
            requires_confirm=True,
            reason=f"Action '{tool}' is {tier.value} — requires confirmation",
        )

    # Check target label escalation
    requires_confirm = False
    if target_label:
        for pattern in _CONFIRM_LABEL_PATTERNS:
            if pattern.search(target_label):
                requires_confirm = True
                break

    # Check sensitive app escalation
    if app_name and not requires_confirm:
        for pattern in _SENSITIVE_APP_PATTERNS:
            if pattern.search(app_name):
                requires_confirm = True
                break

    return SafetyDecision(
        tier=tier,
        allowed=True,
        requires_confirm=requires_confirm,
    )


def classify_tool(tool: str) -> ActionTier:
    """Return the tier for a tool without full evaluation."""
    return _TOOL_TIERS.get(tool, ActionTier.INPUT)
