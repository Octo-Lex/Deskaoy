"""@agent_action decorator and dynamic API description builder."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any


def agent_action(
    func: Callable = None,
    *,
    security_level: str = "sensitive",
    action_class: str = "sensitive",
    impact_level: str = "medium",
    cost_estimate: float = 0.0,
) -> Callable:
    """Decorator marking a method as an agent action.

    Args:
        security_level: One of "safe", "sensitive", "dangerous".
            Defaults to "sensitive". Used by SecurityManager.
        action_class: AI-OS action classification.
            One of: read_only, recoverable, draftable, sensitive, external, irreversible.
            Defaults to "sensitive" (classify UP when unsure).
        impact_level: Impact severity if action goes wrong.
            One of: none, low, medium, high, critical.
            Defaults to "medium".
        cost_estimate: Estimated cost per call in USD. Defaults to 0.0.
    """
    def decorator(fn: Callable) -> Callable:
        fn.is_agent_action = True  # type: ignore[attr-defined]
        fn.security_level = security_level  # type: ignore[attr-defined]
        fn.action_class = action_class  # type: ignore[attr-defined]
        fn.impact_level = impact_level  # type: ignore[attr-defined]
        fn.cost_estimate = cost_estimate  # type: ignore[attr-defined]
        return fn

    if func is not None:
        # Called without arguments: @agent_action
        func.is_agent_action = True  # type: ignore[attr-defined]
        func.security_level = "sensitive"  # type: ignore[attr-defined]
        func.action_class = "sensitive"  # type: ignore[attr-defined]
        func.impact_level = "medium"  # type: ignore[attr-defined]
        func.cost_estimate = 0.0  # type: ignore[attr-defined]
        return func

    # Called with arguments: @agent_action(security_level="safe", action_class="read_only")
    return decorator


def build_action_api_description(controller: Any) -> str:
    methods = []
    for name in sorted(dir(controller)):
        if name.startswith("_"):
            continue
        attr = getattr(controller, name, None)
        if attr is None or not getattr(attr, "is_agent_action", False):
            continue
        sig = inspect.signature(attr)
        doc = inspect.getdoc(attr) or ""
        ac = getattr(attr, "action_class", "sensitive")
        methods.append(
            f"def {name}{sig} -> ActionResult:\n"
            f"    {repr(doc)}\n"
            f"    action_class={ac}"
        )
    header = "Available browser actions:\n"
    return header + "\n\n".join(methods)
