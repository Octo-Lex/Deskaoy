"""ScriptRunner — Declarative automation script execution for Deskaoy.

Loads and executes `.deskaoy.json` files containing action sequences.
Scripts are declarative JSON — no eval/exec of arbitrary code (HB-03).

Schema:
    {
        "name": "My Script",
        "steps": [
            {"action": "click", "target": "OK button"},
            {"action": "type", "value": "Hello World"},
            {"action": "snapshot"},
            {"action": "screenshot"}
        ]
    }

Usage:
    runner = ScriptRunner(agent)
    result = await runner.run(script_path)
    result = await runner.run(script_path, dry_run=True)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Script schema types
# ---------------------------------------------------------------------------

@dataclass
class ScriptStep:
    """A single step in an automation script."""
    action: str
    target: str = ""
    value: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScriptStep:
        """Create a ScriptStep from a dict."""
        return cls(
            action=data.get("action", ""),
            target=data.get("target", ""),
            value=data.get("value", ""),
        )


@dataclass
class ScriptStepResult:
    """Result from executing a single step."""
    step_index: int
    action: str
    ok: bool
    output: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScriptResult:
    """Result from executing a full script."""
    name: str
    ok: bool
    steps_total: int = 0
    steps_ok: int = 0
    steps_failed: int = 0
    step_results: list[ScriptStepResult] = field(default_factory=list)
    dry_run: bool = False

    @property
    def success_rate(self) -> float:
        """Fraction of steps that succeeded."""
        if self.steps_total == 0:
            return 1.0
        return self.steps_ok / self.steps_total


# ---------------------------------------------------------------------------
# Script validation
# ---------------------------------------------------------------------------

class ScriptValidationError(Exception):
    """Raised when a script fails schema validation."""
    pass


def validate_script(data: dict[str, Any]) -> list[str]:
    """Validate a script dict against the expected schema.

    Returns a list of error messages (empty if valid).
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        errors.append("Script must be a JSON object")
        return errors

    # Name is optional but recommended
    name = data.get("name")
    if name is not None and not isinstance(name, str):
        errors.append("'name' must be a string")

    # Steps is required
    steps = data.get("steps")
    if steps is None:
        errors.append("'steps' is required")
        return errors

    if not isinstance(steps, list):
        errors.append("'steps' must be an array")
        return errors

    if len(steps) == 0:
        errors.append("'steps' must not be empty")
        return errors

    # Validate each step
    valid_actions = {
        "click", "type", "fill", "key_press", "scroll",
        "snapshot", "screenshot", "navigate", "observe",
    }

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"Step {i}: must be an object")
            continue

        action = step.get("action")
        if not action:
            errors.append(f"Step {i}: 'action' is required")
            continue

        if not isinstance(action, str):
            errors.append(f"Step {i}: 'action' must be a string")
            continue

        if action not in valid_actions:
            errors.append(
                f"Step {i}: unknown action '{action}' "
                f"(valid: {', '.join(sorted(valid_actions))})"
            )

        # target must be string if present
        target = step.get("target")
        if target is not None and not isinstance(target, str):
            errors.append(f"Step {i}: 'target' must be a string")

        # value must be string if present
        value = step.get("value")
        if value is not None and not isinstance(value, str):
            errors.append(f"Step {i}: 'value' must be a string")

    return errors


def load_script(path: str | Path) -> dict[str, Any]:
    """Load and validate a .deskaoy.json script file.

    Raises:
        FileNotFoundError: If the file does not exist.
        ScriptValidationError: If the script fails validation.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Script not found: {p}")

    with open(p, encoding="utf-8") as f:
        data = json.load(f)

    errors = validate_script(data)
    if errors:
        raise ScriptValidationError(
            "Script validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return data


# ---------------------------------------------------------------------------
# ScriptRunner
# ---------------------------------------------------------------------------

class ScriptRunner:
    """Execute .deskaoy.json automation scripts.

    Each step maps to a DesktopAgent capability. Steps execute sequentially.
    On failure, execution stops (no partial retry).
    """

    # Map script action names to DesktopAgent capabilities
    ACTION_MAP: dict[str, str] = {
        "click": "click",
        "type": "type_text",
        "fill": "fill",
        "key_press": "key_press",
        "scroll": "scroll",
        "snapshot": "snapshot",
        "screenshot": "screenshot",
        "navigate": "navigate",
        "observe": "snapshot",  # observe maps to snapshot in agent
    }

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    async def run(
        self,
        script_path: str | Path,
        *,
        dry_run: bool = False,
    ) -> ScriptResult:
        """Execute a script file.

        Args:
            script_path: Path to the .deskaoy.json file.
            dry_run: If True, validate and show what would be done without executing.

        Returns:
            ScriptResult with per-step outcomes.
        """
        try:
            data = load_script(script_path)
        except (FileNotFoundError, ScriptValidationError, json.JSONDecodeError) as exc:
            return ScriptResult(
                name="<unknown>",
                ok=False,
                step_results=[ScriptStepResult(
                    step_index=0, action="load", ok=False, output=str(exc),
                )],
            )

        name = data.get("name", Path(script_path).stem)
        steps = [ScriptStep.from_dict(s) for s in data["steps"]]

        if dry_run:
            step_results = [
                ScriptStepResult(
                    step_index=i,
                    action=s.action,
                    ok=True,
                    output=f"[dry-run] Would execute: {s.action}"
                           + (f" target={s.target}" if s.target else "")
                           + (f" value={s.value}" if s.value else ""),
                )
                for i, s in enumerate(steps)
            ]
            return ScriptResult(
                name=name,
                ok=True,
                steps_total=len(steps),
                steps_ok=len(steps),
                steps_failed=0,
                step_results=step_results,
                dry_run=True,
            )

        # Execute steps sequentially
        step_results: list[ScriptStepResult] = []
        steps_ok = 0
        steps_failed = 0

        for i, step in enumerate(steps):
            result = await self._execute_step(i, step)
            step_results.append(result)

            if result.ok:
                steps_ok += 1
            else:
                steps_failed += 1
                # Stop on first failure
                break

        return ScriptResult(
            name=name,
            ok=steps_failed == 0,
            steps_total=len(steps),
            steps_ok=steps_ok,
            steps_failed=steps_failed,
            step_results=step_results,
        )

    async def _execute_step(self, index: int, step: ScriptStep) -> ScriptStepResult:
        """Execute a single script step."""
        capability = self.ACTION_MAP.get(step.action)
        if capability is None:
            return ScriptStepResult(
                step_index=index,
                action=step.action,
                ok=False,
                output=f"Unknown action: {step.action}",
            )

        try:
            from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken

            params: dict[str, Any] = {}
            if step.target:
                params["target"] = step.target
            if step.value:
                if step.action == "type":
                    params["text"] = step.value
                else:
                    params["value"] = step.value

            ctx = AgentContext(
                execution_id=f"script-step-{index}",
                idempotency_key=f"script-step-{index}",
                task_id=f"script-step-{index}",
                user_id="script",
                session_id="script-session",
                cancellation_token=CancellationToken(),
            )
            goal = AgentGoal(capability=capability, params=params)
            result = await self._agent.execute(goal, ctx)

            ok = result.status.value == "success"
            output = result.summary

            return ScriptStepResult(
                step_index=index,
                action=step.action,
                ok=ok,
                output=output,
                data={"status": result.status.value},
            )
        except Exception as exc:
            return ScriptStepResult(
                step_index=index,
                action=step.action,
                ok=False,
                output=str(exc),
            )
