"""AppAgent — scoped agent for a single desktop application.

Each AppAgent operates on one application window. It reads relevant
keys from the shared Blackboard before execution, runs an instruction
via the LLM + surface adapter, and writes its outputs back.

The surface adapter is window-scoped — it can only interact with the
target application window, preventing cross-app interference.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from deskaoy.orchestration.blackboard import Blackboard

logger = logging.getLogger(__name__)


@dataclass
class AppAgentConfig:
    """Configuration for a scoped app agent."""

    app_name: str              # Display name: "Outlook", "Notion", "Notepad"
    window_title: str = ""     # Partial match for window title
    max_steps: int = 10        # Max agent loop steps
    timeout: float = 60.0      # Total execution timeout
    reads: list[str] = field(default_factory=list)   # Blackboard keys to read before execution
    writes: list[str] = field(default_factory=list)   # Blackboard keys to write after execution


@dataclass
class AppAgentResult:
    """Result of an AppAgent execution."""

    ok: bool
    app_name: str
    summary: str
    outputs: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    steps: int = 0
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "app_name": self.app_name,
            "summary": self.summary,
            "outputs": self.outputs,
            "duration_ms": self.duration_ms,
            "steps": self.steps,
            "error": self.error,
        }


class AppAgent:
    """A scoped agent that operates on a single application window.

    Lifecycle:
    1. Read blackboard inputs (inject into prompt)
    2. Find and focus the target window
    3. Execute instruction via LLM + surface adapter
    4. Write outputs to blackboard
    5. Return AppAgentResult
    """

    def __init__(
        self,
        config: AppAgentConfig,
        blackboard: Blackboard,
        llm: Any = None,
        surface: Any = None,
    ) -> None:
        self._config = config
        self._blackboard = blackboard
        self._llm = llm
        self._surface = surface

    @property
    def app_name(self) -> str:
        return self._config.app_name

    async def execute(self, instruction: str) -> AppAgentResult:
        """Execute an instruction within this app's scope."""
        start = time.monotonic()

        # 1. Read blackboard inputs
        context_data = await self._read_inputs()

        # 2. Build augmented instruction with context
        augmented = self._augment_instruction(instruction, context_data)

        # 3. Execute via LLM + surface adapter
        try:
            result = await self._run_instruction(augmented)
            duration_ms = (time.monotonic() - start) * 1000

            # 4. Write outputs to blackboard
            await self._write_outputs(result)

            ok = result.get("ok", True)
            error_msg = result.get("error") if not ok else None

            return AppAgentResult(
                ok=ok,
                app_name=self._config.app_name,
                summary=result.get("summary", f"Completed: {instruction[:80]}"),
                outputs=result.get("outputs", {}),
                duration_ms=duration_ms,
                steps=result.get("steps", 0),
                error=error_msg,
            )

        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error("AppAgent(%s) failed: %s", self._config.app_name, exc)
            return AppAgentResult(
                ok=False,
                app_name=self._config.app_name,
                summary=f"Failed: {exc}",
                error=str(exc),
                duration_ms=duration_ms,
            )

    async def _read_inputs(self) -> dict[str, Any]:
        """Read relevant blackboard keys before execution."""
        context_data: dict[str, Any] = {}
        for key in self._config.reads:
            try:
                val = await self._blackboard.read_or_wait(key, timeout=5.0)
                context_data[key] = val
            except (TimeoutError, KeyError):
                logger.debug("AppAgent(%s): blackboard key '%s' not available",
                             self._config.app_name, key)
        return context_data

    def _augment_instruction(self, instruction: str, context: dict[str, Any]) -> str:
        """Inject blackboard context into the instruction."""
        if not context:
            return instruction

        context_lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
        return f"Context from previous steps:\n{context_lines}\n\nInstruction: {instruction}"

    async def _run_instruction(self, instruction: str) -> dict:
        """Run the instruction via LLM + surface adapter.

        Returns a dict with keys: ok, summary, outputs, steps.
        """
        # If no LLM or surface, return a mock result (for testing/pipeline mode)
        if self._llm is None or self._surface is None:
            return {
                "ok": True,
                "summary": f"No-op execution for '{self._config.app_name}'",
                "outputs": {},
                "steps": 0,
            }

        # Use the LLM to propose an action
        prompt = (
            f"You are controlling the application: {self._config.app_name}\n"
            f"Window title: {self._config.window_title or 'unknown'}\n\n"
            f"{instruction}\n\n"
            f"Respond with a JSON action: {{\"action\": \"...\", \"params\": {{...}}, "
            f"\"outputs\": {{\"key\": \"value\"}}, \"summary\": \"...\"}}"
        )

        try:
            response = await self._llm.propose_action(prompt)
        except Exception as exc:
            return {"ok": False, "summary": f"LLM error: {exc}", "outputs": {}, "steps": 0, "error": str(exc)}

        # Execute the proposed action via the surface adapter
        action_name = response.get("action", "")
        action_params = response.get("params", {})
        outputs = response.get("outputs", {})
        summary = response.get("summary", "")

        if not action_name:
            return {"ok": False, "summary": "No action proposed", "outputs": {}, "steps": 0}

        # Dispatch to surface adapter
        method = getattr(self._surface, action_name, None)
        if method is None:
            return {
                "ok": False,
                "summary": f"Unknown action: {action_name}",
                "outputs": {},
                "steps": 0,
            }

        result = method(**action_params)
        if hasattr(result, "__await__"):
            result = await result

        ok = getattr(result, "ok", True)
        return {
            "ok": ok,
            "summary": summary or f"Executed {action_name}",
            "outputs": outputs,
            "steps": 1,
        }

    async def _write_outputs(self, result: dict) -> None:
        """Write declared outputs to the blackboard."""
        outputs = result.get("outputs", {})
        for key in self._config.writes:
            if key in outputs:
                self._blackboard.write(
                    key,
                    outputs[key],
                    writer=f"app_agent.{self._config.app_name}",
                )
