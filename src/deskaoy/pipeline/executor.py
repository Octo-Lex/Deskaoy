"""Pipeline executor — runs deterministic action sequences without LLM.

Receives a :class:`PipelineDefinition`, a :class:`SurfaceAdapter`, and a
dict of arguments.  Steps are dispatched sequentially.  Template expressions
like ``${args.text}`` are resolved before dispatch.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from deskaoy.cascade.protocol import SurfaceAdapter
from deskaoy.pipeline.types import PipelineDefinition
from deskaoy.results.types import ActionResult, action_result

logger = logging.getLogger(__name__)

# Template expression pattern: ${...}
_TEMPLATE_RE = re.compile(r"\$\{([^}]+)\}")


class PipelineState:
    """Accumulates results across pipeline steps."""

    def __init__(self) -> None:
        self.results: list[ActionResult] = []
        self.step_index: int = 0

    def update(self, result: ActionResult) -> None:
        self.results.append(result)
        self.step_index += 1

    @property
    def last_result(self) -> ActionResult | None:
        return self.results[-1] if self.results else None


def _resolve_templates(params: dict[str, Any], args: dict[str, Any], state: PipelineState) -> dict[str, Any]:
    """Resolve ${args.X} and ${state.prev_result} in param values."""
    resolved = {}
    for key, value in params.items():
        if isinstance(value, str):
            def _replacer(match: re.Match) -> str:
                expr = match.group(1).strip()
                # ${args.text}
                if expr.startswith("args."):
                    arg_name = expr[5:]
                    val = args.get(arg_name, "")
                    return str(val)
                # ${state.prev_result.data.X}
                if expr.startswith("state.") and state.last_result:
                    parts = expr[6:].split(".")
                    obj = state.last_result
                    for p in parts:
                        if hasattr(obj, p):
                            obj = getattr(obj, p)
                        elif isinstance(obj, dict):
                            obj = obj.get(p, "")
                        else:
                            return ""
                    return str(obj)
                return match.group(0)

            resolved[key] = _TEMPLATE_RE.sub(_replacer, value)
        else:
            resolved[key] = value
    return resolved


def _eval_condition(condition: str, state: PipelineState) -> bool:
    """Evaluate a simple condition string."""
    if condition == "result.ok":
        return state.last_result.ok if state.last_result else False
    # Conditions that check state we don't have → skip the step
    if condition.startswith("snapshot.contains("):
        return False  # We don't run snapshots in pipeline conditions
    return True


class PipelineExecutor:
    """Execute deterministic pipelines against a SurfaceAdapter."""

    async def execute(
        self,
        pipeline: PipelineDefinition,
        surface: SurfaceAdapter,
        args: dict[str, Any],
    ) -> ActionResult:
        """Run all steps in *pipeline* sequentially.

        Returns the first failed ActionResult, or a success result.
        """
        state = PipelineState()

        for step in pipeline.steps:
            # Condition check
            if step.condition and not _eval_condition(step.condition, state):
                continue

            # Resolve template expressions
            params = _resolve_templates(step.params, args, state)

            # Dispatch
            result = await self._dispatch(surface, step.action, params)

            # Retry on failure
            if not result.ok and step.retry > 0:
                for attempt in range(step.retry):
                    await asyncio.sleep(0.1 * (attempt + 1))
                    result = await self._dispatch(surface, step.action, params)
                    if result.ok:
                        break

            state.update(result)

            if not result.ok:
                return result

        return action_result(ok=True, data={"pipeline": pipeline.name, "steps_completed": state.step_index})

    async def _dispatch(
        self,
        surface: SurfaceAdapter,
        action: str,
        params: dict[str, Any],
    ) -> ActionResult:
        """Dispatch a single action to the SurfaceAdapter."""
        try:
            if action == "click":
                return await surface.click(params.get("target", ""), **{k: v for k, v in params.items() if k != "target"})
            elif action == "fill":
                return await surface.fill(params.get("target", ""), params.get("value", ""), **{k: v for k, v in params.items() if k not in ("target", "value")})
            elif action == "type_text":
                return await surface.type_text(params.get("text", ""))
            elif action == "key_press":
                return await surface.key_press(params.get("key", ""))
            elif action == "scroll":
                return await surface.scroll(params.get("direction", "down"), params.get("amount", 3))
            elif action == "hover":
                return await surface.hover(params.get("target", ""))
            elif action == "snapshot":
                snap = await surface.snapshot()
                return action_result(ok=True, data={"node_count": len(snap.nodes)})
            elif action == "wait":
                await asyncio.sleep(params.get("seconds", 0.5))
                return action_result(ok=True)
            else:
                return action_result(ok=False, data={"error": f"Unknown action: {action}"})
        except Exception as exc:
            return action_result(ok=False, data={"error": str(exc)})
