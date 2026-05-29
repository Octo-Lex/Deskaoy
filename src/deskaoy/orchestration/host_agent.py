"""HostAgent — orchestrates multi-app workflows from a single instruction.

Takes a user instruction, decomposes it into subtasks (via LLM or
template match), assigns each subtask to an AppAgent, and manages
execution via the DAG executor.

This is the top-level coordinator that AI-OS calls into.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from deskaoy.orchestration.app_agent import AppAgent, AppAgentConfig, AppAgentResult
from deskaoy.orchestration.blackboard import Blackboard
from deskaoy.orchestration.dag import DAGExecutor, DAGNode
from deskaoy.orchestration.templates import match_template

logger = logging.getLogger(__name__)


@dataclass
class SubtaskDef:
    """A parsed subtask from LLM decomposition."""

    id: int
    app: str
    instruction: str
    outputs: list[str] = field(default_factory=list)
    depends_on: list[int] = field(default_factory=list)


@dataclass
class SubtaskResult:
    """Result of a single subtask in the orchestration."""

    subtask_id: int
    app: str
    ok: bool
    summary: str
    outputs: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    error: str | None = None


@dataclass
class OrchestratedResult:
    """Result of a full orchestration run."""

    ok: bool
    instruction: str
    subtasks: list[SubtaskResult] = field(default_factory=list)
    blackboard_snapshot: dict[str, Any] = field(default_factory=dict)
    total_duration_ms: float = 0.0
    decomposition_source: str = "none"  # "llm" | "template" | "none"
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "instruction": self.instruction,
            "subtasks": [
                {
                    "id": s.subtask_id,
                    "app": s.app,
                    "ok": s.ok,
                    "summary": s.summary,
                    "outputs": s.outputs,
                    "duration_ms": s.duration_ms,
                }
                for s in self.subtasks
            ],
            "blackboard_snapshot": self.blackboard_snapshot,
            "total_duration_ms": self.total_duration_ms,
            "decomposition_source": self.decomposition_source,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# LLM Decomposition Prompt
# ---------------------------------------------------------------------------

_DECOMPOSE_PROMPT = """\
Decompose this instruction into subtasks for different desktop applications.

Instruction: {instruction}

Respond with ONLY a JSON object (no markdown, no code blocks):
{{
  "subtasks": [
    {{
      "id": 1,
      "app": "app_name",
      "instruction": "what to do in this app",
      "outputs": ["key1", "key2"],
      "depends_on": []
    }},
    {{
      "id": 2,
      "app": "other_app",
      "instruction": "what to do, referencing ${{key1}}",
      "outputs": ["key3"],
      "depends_on": [1]
    }}
  ]
}}

Rules:
- Each subtask targets ONE application
- depends_on lists subtask IDs that must complete first
- outputs are dot-namespaced keys written to shared state (e.g. "email.subject")
- Keep it simple: 2-4 subtasks max
"""


class HostAgent:
    """Orchestrates multi-app desktop workflows.

    Usage:
        host = HostAgent(llm=my_llm)
        result = await host.orchestrate("Read email and create a task in Notion")
    """

    def __init__(
        self,
        llm: Any = None,
        *,
        surface_factory: Callable[[str], Any] | None = None,
        abort_on_failure: bool = True,
    ) -> None:
        self._llm = llm
        self._surface_factory = surface_factory
        self._abort_on_failure = abort_on_failure

    async def orchestrate(self, instruction: str) -> OrchestratedResult:
        """Orchestrate a multi-app workflow from a single instruction."""
        start = time.monotonic()

        # 1. Try template match first (zero-LLM)
        template = match_template(instruction)
        if template is not None:
            subtasks = self._template_to_subtasks(template)
            source = "template"
        elif self._llm is not None:
            # 2. LLM decomposition
            try:
                subtasks = await self._decompose(instruction)
                source = "llm"
            except Exception as exc:
                duration_ms = (time.monotonic() - start) * 1000
                return OrchestratedResult(
                    ok=False,
                    instruction=instruction,
                    total_duration_ms=duration_ms,
                    decomposition_source="llm",
                    error=f"Decomposition failed: {exc}",
                )
        else:
            return OrchestratedResult(
                ok=False,
                instruction=instruction,
                decomposition_source="none",
                error="No LLM or template match for decomposition",
            )

        if not subtasks:
            duration_ms = (time.monotonic() - start) * 1000
            return OrchestratedResult(
                ok=False,
                instruction=instruction,
                total_duration_ms=duration_ms,
                decomposition_source=source,
                error="Decomposition returned no subtasks",
            )

        # 3. Execute via DAG
        blackboard = Blackboard()
        result = await self._execute_dag(subtasks, blackboard)
        duration_ms = (time.monotonic() - start) * 1000

        # Build orchestrated result
        all_ok = all(s.ok for s in result)
        return OrchestratedResult(
            ok=all_ok,
            instruction=instruction,
            subtasks=result,
            blackboard_snapshot=blackboard.snapshot(),
            total_duration_ms=duration_ms,
            decomposition_source=source,
        )

    async def _decompose(self, instruction: str) -> list[SubtaskDef]:
        """Ask the LLM to decompose an instruction into subtasks."""
        prompt = _DECOMPOSE_PROMPT.format(instruction=instruction)
        response = await self._llm.propose_action(prompt)

        # Parse the response
        if isinstance(response, dict):
            data = response
        elif isinstance(response, str):
            data = self._parse_json_response(response)
        else:
            raise ValueError(f"Unexpected LLM response type: {type(response)}")

        subtasks_raw = data.get("subtasks", [])
        if not subtasks_raw:
            raise ValueError("LLM returned no subtasks")

        return [
            SubtaskDef(
                id=int(s.get("id", i + 1)),
                app=s.get("app", "unknown"),
                instruction=s.get("instruction", ""),
                outputs=s.get("outputs", []),
                depends_on=[int(d) for d in s.get("depends_on", [])],
            )
            for i, s in enumerate(subtasks_raw)
        ]

    def _parse_json_response(self, text: str) -> dict:
        """Extract JSON from LLM response text."""
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code block
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding first { ... } block
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not parse JSON from LLM response: {text[:200]}")

    def _template_to_subtasks(self, template: dict) -> list[SubtaskDef]:
        """Convert a template definition to SubtaskDefs."""
        return [
            SubtaskDef(
                id=int(s.get("id", i + 1)),
                app=s.get("app", "unknown"),
                instruction=s.get("instruction", ""),
                outputs=s.get("outputs", []),
                depends_on=[int(d) for d in s.get("depends_on", [])],
            )
            for i, s in enumerate(template.get("subtasks", []))
        ]

    async def _execute_dag(
        self,
        subtasks: list[SubtaskDef],
        blackboard: Blackboard,
    ) -> list[SubtaskResult]:
        """Build DAGNodes from subtasks and execute."""
        # Create AppAgents
        agents: dict[int, AppAgent] = {}
        for st in subtasks:
            config = AppAgentConfig(
                app_name=st.app,
                reads=[k for dep_id in st.depends_on for k in
                       next((s.outputs for s in subtasks if s.id == dep_id), [])],
                writes=st.outputs,
                max_steps=10,
                timeout=60.0,
            )
            surface = None
            if self._surface_factory:
                try:
                    surface = self._surface_factory(st.app)
                except Exception:
                    logger.debug("Surface factory failed for %s", st.app)
            agent = AppAgent(
                config=config,
                blackboard=blackboard,
                llm=self._llm,
                surface=surface,
            )
            agents[st.id] = agent

        # Build DAG nodes
        dag_nodes = [
            DAGNode(
                id=st.id,
                action=lambda ag=agents[st.id], instr=st.instruction: ag.execute(instr),
                depends_on=st.depends_on,
                outputs=st.outputs,
                label=st.app,
            )
            for st in subtasks
        ]

        # Execute
        executor = DAGExecutor(abort_on_failure=self._abort_on_failure)
        dag_results = await executor.execute(dag_nodes)

        # Map DAGNodeResults to SubtaskResults
        subtask_map = {st.id: st for st in subtasks}
        results: list[SubtaskResult] = []
        for dr in dag_results:
            st = subtask_map.get(dr.node_id)
            app_result = None
            if dr.ok and isinstance(dr.result, AppAgentResult):
                app_result = dr.result

            results.append(SubtaskResult(
                subtask_id=dr.node_id,
                app=st.app if st else "unknown",
                ok=dr.ok and (app_result.ok if app_result else False),
                summary=app_result.summary if app_result else (dr.error or "Failed"),
                outputs=app_result.outputs if app_result else {},
                duration_ms=dr.duration_ms,
                error=dr.error if not dr.ok else (app_result.error if app_result and not app_result.ok else None),
            ))

        return results
