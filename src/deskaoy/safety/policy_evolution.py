"""Policy Self-Evolution — learn from denials instead of just blocking.

When a policy denial occurs, analyze the denial reason and propose a
minimal policy change.  The user (via a configurable handler) can:
  - add_to_policy: apply the change permanently (persist)
  - allow_once:    apply the change in-memory only (one-session override)
  - deny:          keep blocking

Budget and session violations are intentionally NOT suggestible — they
represent hard limits, not missing permissions.

Pattern source: deterministic-agent-control-protocol (det-acp) evolution/
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class DenialCategory(StrEnum):
    NO_CAPABILITY = "no_capability"
    SCOPE_VIOLATION = "scope_violation"
    FORBIDDEN_MATCH = "forbidden_match"
    BUDGET_EXCEEDED = "budget_exceeded"       # NOT suggestible
    SESSION_CONSTRAINT = "session_constraint"  # NOT suggestible
    UNKNOWN = "unknown"


class EvolutionDecision(StrEnum):
    ADD_TO_POLICY = "add_to_policy"   # Mutate policy + persist
    ALLOW_ONCE = "allow_once"         # In-memory override only
    DENY = "deny"                     # Keep blocking


@dataclass
class PolicySuggestion:
    """A proposed policy change that would allow a previously denied action."""
    category: DenialCategory
    tool: str
    description: str   # Human-readable: 'Add "click" capability for domain "example.com"?'
    change: dict        # Type-specific change payload:
                        #   add_capability:  {"type": "add_capability", "tool": str, "scope": dict}
                        #   widen_scope:     {"type": "widen_scope", "tool": str, "field": str, "add": list}
                        #   remove_forbidden: {"type": "remove_forbidden", "pattern": str}


@dataclass
class EvolutionResult:
    """Outcome of the evolution handler after the user has responded."""
    decision: EvolutionDecision
    suggestion: PolicySuggestion


# Handler callback — present suggestion to user, return their decision.
EvolutionHandler = Callable[[PolicySuggestion], Awaitable[EvolutionDecision]]


# ---------------------------------------------------------------------------
# Suggestion engine
# ---------------------------------------------------------------------------

def suggest_policy_change(
    action: str,
    reason: str,
) -> PolicySuggestion | None:
    """Pattern-match a denial reason and propose a minimal policy change.

    Returns None if the denial is not fixable via policy evolution
    (budget exceeded, session constraint, or unknown reason).
    """
    if not reason:
        return None

    # 1. "No capability defined for tool 'X'"
    m = re.match(r"No capability defined for tool ['\"](\S+)['\"]", reason)
    if m:
        tool = m.group(1)
        return PolicySuggestion(
            category=DenialCategory.NO_CAPABILITY,
            tool=tool,
            description=f'Add "{tool}" capability to the policy?',
            change={"type": "add_capability", "tool": tool, "scope": {}},
        )

    # 2. "No capability for action 'X'" (our variant)
    m = re.match(r"No capability for action ['\"](\S+)['\"]", reason)
    if m:
        tool = m.group(1)
        return PolicySuggestion(
            category=DenialCategory.NO_CAPABILITY,
            tool=tool,
            description=f'Add "{tool}" action capability to the policy?',
            change={"type": "add_capability", "tool": tool, "scope": {}},
        )

    # 3. Path scope: "Path 'X' is outside allowed scope"
    m = re.match(r"Path ['\"](.+?)['\"] is outside allowed scope", reason)
    if m:
        path = m.group(1)
        return PolicySuggestion(
            category=DenialCategory.SCOPE_VIOLATION,
            tool=action,
            description=f'Add path "{path}" to "{action}" scope?',
            change={"type": "widen_scope", "tool": action, "field": "paths", "add": [path]},
        )

    # 4. Domain scope: "Domain 'X' is not in allowed list"
    m = re.match(r"Domain ['\"](.+?)['\"] is not in allowed list", reason)
    if m:
        domain = m.group(1)
        return PolicySuggestion(
            category=DenialCategory.SCOPE_VIOLATION,
            tool=action,
            description=f'Add domain "{domain}" to "{action}" scope?',
            change={"type": "widen_scope", "tool": action, "field": "domains", "add": [domain]},
        )

    # 5. Action blocked by policy (generic scope violation)
    if "blocked by policy" in reason.lower():
        return PolicySuggestion(
            category=DenialCategory.SCOPE_VIOLATION,
            tool=action,
            description=f'Allow "{action}" — currently blocked by policy?',
            change={"type": "widen_scope", "tool": action, "field": "actions", "add": [action]},
        )

    # 6. Forbidden pattern: matches forbidden pattern "X"
    m = re.search(r"forbidden pattern ['\"](.+?)['\"]", reason, re.IGNORECASE)
    if m:
        pattern = m.group(1)
        return PolicySuggestion(
            category=DenialCategory.FORBIDDEN_MATCH,
            tool=action,
            description=f'Remove forbidden pattern "{pattern}" from policy? '
                        f'(Warning: this loosens security restrictions)',
            change={"type": "remove_forbidden", "pattern": pattern},
        )

    # 7. Budget / session violations — NOT suggestible
    if _is_hard_limit(reason):
        return None

    # Unknown — NOT suggestible
    return None


def _is_hard_limit(reason: str) -> bool:
    """Return True if the denial reason represents a hard limit (not suggestible)."""
    budget_keywords = [
        "budget exceeded",
        "budget limit",
        "cost limit",
        "rate limit",
        "session action limit",
        "session denial limit",
        "session duration limit",
    ]
    reason_lower = reason.lower()
    return any(kw in reason_lower for kw in budget_keywords)


# ---------------------------------------------------------------------------
# Evolution engine
# ---------------------------------------------------------------------------

class PolicyEvolutionEngine:
    """Orchestrates policy evolution: suggest → ask user → apply.

    Usage::

        engine = PolicyEvolutionEngine(handler=my_handler)
        suggestion = engine.suggest("click", "No capability defined for tool 'click'")
        if suggestion:
            result = await engine.evolve(suggestion)
            if result.decision == EvolutionDecision.ADD_TO_POLICY:
                engine.apply_change(suggestion, policy)
    """

    def __init__(
        self,
        handler: EvolutionHandler | None = None,
        timeout_ms: int = 30_000,
    ) -> None:
        self._handler = handler
        self._timeout_ms = timeout_ms

    def suggest(
        self,
        action: str,
        reason: str,
    ) -> PolicySuggestion | None:
        """Analyze a denial and return a suggestion (or None)."""
        return suggest_policy_change(action, reason)

    async def evolve(self, suggestion: PolicySuggestion) -> EvolutionResult:
        """Present suggestion to handler and return the decision.

        If no handler is configured, returns DENY.
        If handler times out, returns DENY.
        """
        if self._handler is None:
            return EvolutionResult(
                decision=EvolutionDecision.DENY,
                suggestion=suggestion,
            )

        try:
            decision = await asyncio.wait_for(
                self._handler(suggestion),
                timeout=self._timeout_ms / 1000.0,
            )
        except TimeoutError:
            logger.warning(
                "Policy evolution handler timed out (%dms) for %s",
                self._timeout_ms, suggestion.tool,
            )
            decision = EvolutionDecision.DENY
        except Exception as exc:
            logger.warning("Policy evolution handler error: %s", exc)
            decision = EvolutionDecision.DENY

        return EvolutionResult(
            decision=decision,
            suggestion=suggestion,
        )

    def apply_change(
        self,
        suggestion: PolicySuggestion,
        policy: Any,
    ) -> None:
        """Apply a suggestion's change to a policy object.

        The policy object must support:
          - For add_capability: `enabled_actions` list attribute
          - For widen_scope: depends on policy structure
          - For remove_forbidden: `forbidden_patterns` list attribute

        This mutates the policy in-place.  Caller is responsible for
        persistence if EvolutionDecision was ADD_TO_POLICY.
        """
        change = suggestion.change
        change_type = change.get("type", "")

        if change_type == "add_capability":
            tool = change.get("tool", suggestion.tool)
            if hasattr(policy, "enabled_actions") and isinstance(policy.enabled_actions, list):
                if tool not in policy.enabled_actions:
                    policy.enabled_actions.append(tool)
                    logger.info("Policy evolution: added capability '%s'", tool)

        elif change_type == "widen_scope":
            field_name = change.get("field", "")
            values = change.get("add", [])
            if hasattr(policy, "scope") and isinstance(policy.scope, dict):
                scope_list = policy.scope.setdefault(field_name, [])
                for v in values:
                    if v not in scope_list:
                        scope_list.append(v)
                logger.info("Policy evolution: widened scope '%s' by %s", field_name, values)

        elif change_type == "remove_forbidden":
            pattern = change.get("pattern", "")
            if hasattr(policy, "forbidden_patterns") and isinstance(policy.forbidden_patterns, list):
                if pattern in policy.forbidden_patterns:
                    policy.forbidden_patterns.remove(pattern)
                    logger.info("Policy evolution: removed forbidden pattern '%s'", pattern)
