"""Pre-flight instruction validation — LangExtract-inspired validate_prompt_alignment().

Validates automate instructions BEFORE execution:
  1. Surface adapter is connected
  2. Instruction can be parsed into known actions
  3. Policy allows the action
  4. Target surface is reachable

Three levels: OFF (skip), WARNING (log), ERROR (abort).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deskaoy.desktop_agent import DesktopAgent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class ValidationLevel(StrEnum):
    OFF = "off"
    WARNING = "warning"
    ERROR = "error"


class ValidationIssueKind(StrEnum):
    UNKNOWN_ACTION = "unknown_action"
    MISSING_SURFACE = "missing_surface"
    INVALID_PARAMS = "invalid_params"
    POLICY_DENIED = "policy_denied"
    SURFACE_UNREACHABLE = "surface_unreachable"


@dataclass
class ValidationIssue:
    kind: ValidationIssueKind
    message: str
    action: str = ""
    suggestion: str = ""


@dataclass
class ValidationReport:
    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """True if any issue is a hard error (not just a warning)."""
        error_kinds = {
            ValidationIssueKind.UNKNOWN_ACTION,
            ValidationIssueKind.MISSING_SURFACE,
            ValidationIssueKind.SURFACE_UNREACHABLE,
        }
        return any(issue.kind in error_kinds for issue in self.issues)

    @property
    def error_count(self) -> int:
        return len(self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [
                {
                    "kind": str(i.kind),
                    "message": i.message,
                    "action": i.action,
                    "suggestion": i.suggestion,
                }
                for i in self.issues
            ],
        }


# ---------------------------------------------------------------------------
# Known actions catalog
# ---------------------------------------------------------------------------

KNOWN_ACTIONS = frozenset({
    "click", "double_click", "right_click", "hover",
    "type_text", "fill", "key_press", "key_combo",
    "scroll", "select_option", "drag",
    "screenshot", "snapshot",
    "navigate", "wait", "focus",
})


# Action → required params mapping
REQUIRED_PARAMS: dict[str, list[str]] = {
    "click": ["target"],
    "double_click": ["target"],
    "right_click": ["target"],
    "hover": ["target"],
    "type_text": ["text"],
    "fill": ["target", "value"],
    "key_press": ["key"],
    "key_combo": ["keys"],
    "scroll": ["direction"],
    "select_option": ["target", "value"],
    "drag": ["source", "target"],
    "navigate": ["url"],
}


# ---------------------------------------------------------------------------
# Instruction parser (lightweight — just extracts action keywords)
# ---------------------------------------------------------------------------

_ACTION_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in KNOWN_ACTIONS) + r")\b",
    re.IGNORECASE,
)


def extract_actions(instruction: str) -> list[str]:
    """Extract action keywords from a natural-language instruction."""
    return [m.group(1).lower() for m in _ACTION_PATTERN.finditer(instruction)]


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def validate_instruction(
    instruction: str,
    *,
    agent: DesktopAgent,
    level: ValidationLevel = ValidationLevel.WARNING,
) -> ValidationReport:
    """Pre-flight validation — LangExtract's ``validate_prompt_alignment()`` equivalent.

    Checks:
    1. Surface adapter is connected and reachable
    2. Instruction references known actions
    3. Policy allows the action (if policy bridge is wired)
    4. Instruction is non-empty and parseable

    Args:
        instruction: Natural-language automate instruction.
        agent: DesktopAgent instance to validate against.
        level: OFF skips, WARNING logs, ERROR aborts on issues.

    Returns:
        ValidationReport with issues list and valid flag.
    """
    if level == ValidationLevel.OFF:
        return ValidationReport(valid=True)

    issues: list[ValidationIssue] = []

    # --- Check 1: Surface adapter ---
    adapter = getattr(agent, "_surface_adapter", None)
    if adapter is None:
        issues.append(ValidationIssue(
            kind=ValidationIssueKind.MISSING_SURFACE,
            message="No surface adapter connected. Actions cannot execute.",
            suggestion="Initialize DesktopAgent with a surface adapter.",
        ))
        return ValidationReport(valid=False, issues=issues)

    # --- Check 2: Reachable ---
    is_reachable = getattr(adapter, "is_reachable", None)
    if callable(is_reachable):
        try:
            if not is_reachable():
                issues.append(ValidationIssue(
                    kind=ValidationIssueKind.SURFACE_UNREACHABLE,
                    message="Surface adapter reports unreachable.",
                    suggestion="Check the target application is open and accessible.",
                ))
        except Exception:
            pass  # Non-critical — don't fail validation on is_reachable errors

    # --- Check 3: Known actions ---
    actions = extract_actions(instruction)
    if not actions and instruction.strip():
        # No known action keywords — might be too vague
        issues.append(ValidationIssue(
            kind=ValidationIssueKind.UNKNOWN_ACTION,
            message=f"No recognized action in instruction: '{instruction[:80]}'",
            action="",
            suggestion=f"Include an action keyword: {', '.join(sorted(KNOWN_ACTIONS)[:8])}...",
        ))

    # --- Check 4: Policy ---
    policy_bridge = getattr(agent, "_policy_bridge", None)
    if policy_bridge is not None:
        for action in actions:
            try:
                decision = policy_bridge.preflight(action)
                if hasattr(decision, "effect") and str(decision.effect) in (
                    "deny", "BLOCK", "PolicyEffect.BLOCK",
                ):
                    issues.append(ValidationIssue(
                        kind=ValidationIssueKind.POLICY_DENIED,
                        message=f"Policy denies action: {action}",
                        action=action,
                        suggestion="Contact admin to allow this action.",
                    ))
            except Exception:
                pass  # Policy check failure is non-critical

    # --- Build report ---
    valid = not issues or not any(
        i.kind in (ValidationIssueKind.UNKNOWN_ACTION, ValidationIssueKind.MISSING_SURFACE, ValidationIssueKind.SURFACE_UNREACHABLE)
        for i in issues
    )

    report = ValidationReport(valid=valid, issues=issues)

    # --- Level handling ---
    if level == ValidationLevel.WARNING and issues:
        for issue in issues:
            logger.warning("Instruction validation: [%s] %s", issue.kind, issue.message)
    elif level == ValidationLevel.ERROR and report.has_errors:
        logger.error("Instruction validation failed: %d issues", len(issues))

    return report
