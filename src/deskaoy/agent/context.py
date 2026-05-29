"""Step context window — LangExtract-inspired context_window_chars for agent loop.

Carries previous step's state (action, result, snapshot summary) into the
next step's LLM prompt, analogous to LangExtract's chunk context window
that carries characters from the previous chunk for coreference resolution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step context
# ---------------------------------------------------------------------------

@dataclass
class StepContext:
    """Carries previous step's state into the current LLM prompt.

    LangExtract analog: ``context_window_chars`` prepends characters from the
    previous chunk. Deskaoy analog: prepend previous step's action +
    result + snapshot summary.

    This helps the LLM understand:
    - What just happened (coreference: "click it" → what is "it"?)
    - What went wrong (error history)
    - What's been tried (action history, prevents loops)
    """

    # Previous step summary
    prev_action: str = ""           # "click(target=Submit button)"
    prev_result: str = ""           # "ok" | "failed: not_found"

    # Rolling window (last N steps)
    recent_actions: list[str] = field(default_factory=list)
    recent_results: list[str] = field(default_factory=list)
    errors_so_far: list[str] = field(default_factory=list)

    # Surface state
    current_url: str = ""
    current_title: str = ""

    # Budget
    max_context_chars: int = 500

    def to_prompt_text(self) -> str:
        """Format as LLM-consumable context block.

        Returns a compact text block summarizing recent context,
        analogous to LangExtract's prepended chunk context.
        """
        lines: list[str] = []

        if self.prev_action:
            result_str = self.prev_result or "ok"
            lines.append(f"Previous action: {self.prev_action} → {result_str}")

        if self.recent_actions:
            # Last 5 actions, compact format
            recent = self.recent_actions[-5:]
            lines.append("Recent actions: " + "; ".join(recent))

        if self.errors_so_far:
            # Last 3 errors
            errors = self.errors_so_far[-3:]
            lines.append("Errors so far: " + "; ".join(errors))

        if self.current_url:
            lines.append(f"Current URL: {self.current_url}")

        if self.current_title:
            lines.append(f"Current title: {self.current_title}")

        text = "\n".join(lines)

        # Enforce budget
        if len(text) > self.max_context_chars:
            text = text[: self.max_context_chars - 3] + "..."

        return text

    @property
    def has_context(self) -> bool:
        """Whether there's any context to include."""
        return bool(self.prev_action or self.recent_actions or self.errors_so_far)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prev_action": self.prev_action,
            "prev_result": self.prev_result,
            "recent_actions": self.recent_actions[-5:],
            "recent_results": self.recent_results[-5:],
            "errors_so_far": self.errors_so_far[-3:],
            "current_url": self.current_url,
            "current_title": self.current_title,
        }


# ---------------------------------------------------------------------------
# Context builder (used by AgentLoop)
# ---------------------------------------------------------------------------

def build_step_context(
    steps: list[Any],
    *,
    max_actions: int = 5,
    max_errors: int = 3,
    current_url: str = "",
    current_title: str = "",
) -> StepContext:
    """Build a StepContext from the step history.

    Args:
        steps: List of StepResult objects from the agent loop.
        max_actions: Maximum recent actions to include.
        max_errors: Maximum errors to include.
        current_url: Current surface URL/title.
        current_title: Current surface title.

    Returns:
        StepContext populated with recent step data.
    """
    if not steps:
        return StepContext(current_url=current_url, current_title=current_title)

    last = steps[-1]

    # Build action summary for last step
    prev_action = _format_action(last)
    prev_result = "ok" if not getattr(last, "error", None) else f"failed: {last.error}"

    # Rolling window of recent actions
    recent_actions = [_format_action(s) for s in steps[-max_actions:]]
    recent_results = [
        "ok" if not getattr(s, "error", None) else f"failed: {s.error}"
        for s in steps[-max_actions:]
    ]

    # Error history
    errors_so_far = [
        f"step {s.step_number}: {s.error}"
        for s in steps
        if getattr(s, "error", None)
    ][-max_errors:]

    return StepContext(
        prev_action=prev_action,
        prev_result=prev_result,
        recent_actions=recent_actions,
        recent_results=recent_results,
        errors_so_far=errors_so_far,
        current_url=current_url,
        current_title=current_title,
    )


def _format_action(step: Any) -> str:
    """Format a step result into a compact action string."""
    name = getattr(step, "action_name", "unknown")
    params = getattr(step, "action_params", {})
    # Compact: "click(target=Submit)" instead of full dict
    if params:
        target = params.get("target") or params.get("text") or params.get("key") or params.get("url", "")
        if target:
            return f"{name}({target})"
    return name
