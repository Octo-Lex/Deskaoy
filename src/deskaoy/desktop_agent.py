"""DesktopAgent — AI-OS Agent Protocol implementation for desktop automation.

This is the citizen-facing surface. The AI-OS platform calls
execute(goal, context) → AgentResult, and the DesktopAgent delegates
to the internal engine (AgentLoop + SurfaceAdapter + cascade).

The DesktopAgent owns the "desktop_automation" domain.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from deskaoy._version import resolve_version
from deskaoy.hooks import HookContext, HookName
from deskaoy.hooks import hooks as global_hooks
from deskaoy.memory.fact_extractor import FactExtractor
from deskaoy.memory.facts import FactStore
from deskaoy.memory.store import ActionMemory
from deskaoy.memory.types import ActionEvidence
from deskaoy.os_types import (
    AgentContext,
    AgentEstimate,
    AgentGoal,
    AgentResult,
    Confidence,
    ErrorCode,
    Issue,
    IssueSeverity,
    Learning,
    MutationRecord,
    OperationCancelled,
    RestoreMethod,
    ResultStatus,
    Snapshot,
    UndoResult,
)
from deskaoy.pipeline.executor import PipelineExecutor
from deskaoy.pipeline.registry import PipelineRegistry
from deskaoy.policy import PolicyBridge, PolicyDecision, PolicyEffect
from deskaoy.recovery_bridge import RecoveryBridge
from deskaoy.result_mapper import map_action_result
from deskaoy.results.types import ActionResult
from deskaoy.routines import RoutineScheduler
from deskaoy.safety.action_validator import validate_action
from deskaoy.safety.compensation import (
    CompensationEngine,
    CompensationPlan,
)
from deskaoy.safety.cost_tracker import CostTracker
from deskaoy.safety.evidence_ledger import EvidenceLedger
from deskaoy.safety.health import HealthCheck, HealthStatus
from deskaoy.safety.latency_budget import LatencyBudget
from deskaoy.safety.policy_evolution import (
    EvolutionDecision,
    PolicyEvolutionEngine,
)
from deskaoy.safety.rate_governor import ActionRateGovernor
from deskaoy.safety.resource_tracker import ResourceTracker
from deskaoy.safety.session_budget import (
    SessionBudget,
    SessionBudgetTracker,
    SessionLimits,
)
from deskaoy.skills.loader import SkillLoader
from deskaoy.storage import StorageResolver
from deskaoy.trace_bridge import ActionSpan, TraceBridge
from deskaoy.validation import ValidationLevel, validate_instruction
from deskaoy.verification.grounding import verify_grounding

logger = logging.getLogger(__name__)

# Module-level pipeline registry (populated with builtins on first use)
_pipeline_registry: PipelineRegistry | None = None


def _get_pipeline_registry() -> PipelineRegistry:
    """Lazy-init the pipeline registry with built-in pipelines."""
    global _pipeline_registry
    if _pipeline_registry is None:
        _pipeline_registry = PipelineRegistry()
        from deskaoy.pipeline.builtins.notepad_type import NOTEPAD_TYPE
        _pipeline_registry.register(NOTEPAD_TYPE)
    return _pipeline_registry


# ---------------------------------------------------------------------------
# Capability registry — maps SurfaceAdapter methods to AI-OS metadata
# ---------------------------------------------------------------------------

CAPABILITIES: dict[str, dict[str, Any]] = {
    "click": {
        "description": "Click on a desktop element identified by text, coordinates, or description",
        "action_class": "sensitive",
        "impact_level": "low",
        "cost_estimate": 0.001,
        "method": "click",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Element name, auto:id, or x,y coordinates"},
                "button": {"type": "string", "enum": ["left", "right", "double"], "default": "left"},
            },
            "required": ["target"],
        },
        "output_schema": {
            "status": {"type": "string", "enum": ["success", "failure", "dry_run"]},
            "confidence": {"type": "number", "description": "0.0-1.0 execution fidelity"},
            "mutations": {"type": "array", "description": "State changes (before/after)"},
            "undo": {"type": "object", "description": "Compensation plan to reverse this action"},
        },
    },
    "fill": {
        "description": "Fill a text input field with a value",
        "action_class": "sensitive",
        "impact_level": "medium",
        "cost_estimate": 0.001,
        "method": "fill",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Input field element name or selector"},
                "value": {"type": "string", "description": "Text value to fill into the field"},
                "clear_first": {"type": "boolean", "default": True, "description": "Clear existing text before filling"},
            },
            "required": ["target", "value"],
        },
        "output_schema": {
            "status": {"type": "string", "enum": ["success", "failure", "dry_run"]},
            "confidence": {"type": "number"},
            "mutations": {"type": "array"},
            "undo": {"type": "object"},
        },
    },
    "type_text": {
        "description": "Type text character by character with human-like delays",
        "action_class": "sensitive",
        "impact_level": "medium",
        "cost_estimate": 0.001,
        "method": "type_text",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text string to type"},
                "delay_ms": {"type": "number", "default": 30, "description": "Delay between keystrokes in milliseconds"},
            },
            "required": ["text"],
        },
        "output_schema": {
            "status": {"type": "string", "enum": ["success", "failure", "dry_run"]},
            "confidence": {"type": "number"},
            "mutations": {"type": "array"},
        },
    },
    "key_press": {
        "description": "Press a key with optional modifiers",
        "action_class": "recoverable",
        "impact_level": "low",
        "cost_estimate": 0.0,
        "method": "key_press",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key name (e.g. 'enter', 'tab', 'a')"},
                "modifiers": {"type": "array", "items": {"type": "string", "enum": ["ctrl", "alt", "shift", "win"]}, "description": "Modifier keys"},
                "combo": {"type": "string", "description": "Key combo string (e.g. 'ctrl+s', 'alt+f4')"},
            },
            "required": [],
        },
        "output_schema": {
            "status": {"type": "string", "enum": ["success", "failure"]},
            "confidence": {"type": "number"},
        },
    },
    "scroll": {
        "description": "Scroll in a direction by a pixel amount",
        "action_class": "read_only",
        "impact_level": "none",
        "cost_estimate": 0.0,
        "method": "scroll",
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"], "default": "down"},
                "amount": {"type": "number", "default": 300, "description": "Scroll distance in pixels"},
            },
            "required": [],
        },
        "output_schema": {
            "status": {"type": "string", "enum": ["success", "failure"]},
            "confidence": {"type": "number"},
        },
    },
    "screenshot": {
        "description": "Capture a screenshot of the desktop or focused window",
        "action_class": "read_only",
        "impact_level": "none",
        "cost_estimate": 0.0,
        "method": "screenshot",
        "input_schema": {
            "type": "object",
            "properties": {
                "region": {"type": "string", "description": "Screen region to capture (e.g. '0,0,800,600')"},
                "window": {"type": "string", "description": "Capture specific window by title"},
            },
            "required": [],
        },
        "output_schema": {
            "status": {"type": "string", "enum": ["success", "failure"]},
            "data": {"type": "object", "properties": {"image_base64": {"type": "string"}, "width": {"type": "integer"}, "height": {"type": "integer"}}},
            "artifacts": {"type": "array", "description": "Image resource references"},
        },
    },
    "snapshot": {
        "description": "Capture the accessibility tree of the current surface",
        "action_class": "read_only",
        "impact_level": "none",
        "cost_estimate": 0.0,
        "method": "snapshot",
        "input_schema": {
            "type": "object",
            "properties": {
                "depth": {"type": "integer", "default": -1, "description": "Max tree depth (-1 = unlimited)"},
                "filter": {"type": "string", "description": "Filter elements by role or name pattern"},
            },
            "required": [],
        },
        "output_schema": {
            "status": {"type": "string", "enum": ["success", "failure"]},
            "data": {"type": "object", "properties": {"element_count": {"type": "integer"}, "tree": {"type": "object"}}},
            "confidence": {"type": "number"},
        },
    },
    "navigate": {
        "description": "Navigate to a URL or open a file/application",
        "action_class": "read_only",
        "impact_level": "low",
        "cost_estimate": 0.0,
        "method": "navigate",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "URL, file path, or application name"},
            },
            "required": ["target"],
        },
        "output_schema": {
            "status": {"type": "string", "enum": ["success", "failure"]},
            "confidence": {"type": "number"},
        },
    },
    "automate": {
        "description": "Execute a multi-step desktop automation goal using the agent loop",
        "action_class": "sensitive",
        "impact_level": "high",
        "cost_estimate": 0.02,
        "method": None,  # Uses AgentLoop, not a single adapter call
        "input_schema": {
            "type": "object",
            "properties": {
                "instruction": {"type": "string", "description": "Natural-language instruction describing the task"},
            },
            "required": ["instruction"],
        },
        "output_schema": {
            "status": {"type": "string", "enum": ["success", "partial", "failure", "cancelled"]},
            "confidence": {"type": "number"},
            "data": {"type": "object", "properties": {"steps": {"type": "array"}, "completion_reason": {"type": "string"}}},
            "mutations": {"type": "array"},
            "undo": {"type": "object"},
        },
    },
    "orchestrate": {
        "description": "Orchestrate a multi-app workflow from a single instruction",
        "action_class": "sensitive",
        "impact_level": "high",
        "cost_estimate": 0.05,
        "method": None,  # Uses HostAgent + DAG
        "input_schema": {
            "type": "object",
            "properties": {
                "instruction": {"type": "string", "description": "Natural-language instruction for multi-app workflow"},
            },
            "required": ["instruction"],
        },
        "output_schema": {
            "status": {"type": "string", "enum": ["success", "partial", "failure"]},
            "confidence": {"type": "number"},
            "data": {"type": "object", "properties": {"subtasks": {"type": "array"}}},
            "mutations": {"type": "array"},
        },
    },
}

CAPABILITY_NAMES = list(CAPABILITIES.keys())
CAPABILITY_DESCRIPTIONS = {k: v["description"] for k, v in CAPABILITIES.items()}
ACTION_CLASSES = {k: v["action_class"] for k, v in CAPABILITIES.items()}


class DesktopAgent:
    """AI-OS Agent Protocol implementation for desktop automation.

    Owns the "desktop_automation" domain. Wraps the internal engine
    (AgentLoop + SurfaceAdapter) behind the contract interface.

    Usage:
        agent = DesktopAgent(surface=my_adapter, llm=my_llm)
        result = await agent.execute(goal, context)
    """

    # ─── Identity ─────────────────────────────────
    name: str = "deskaoy"
    display_name: str = "Deskaoy"
    description: str = (
        "Automates desktop interactions: clicking, typing, scrolling, "
        "and multi-step workflows across native applications."
    )
    version: str = resolve_version()  # from installed metadata, fallback to constant
    domains: list[str] = ["desktop_automation"]

    # ─── Capabilities ────────────────────────────
    capabilities: list[str] = CAPABILITY_NAMES
    capability_descriptions: dict[str, str] = CAPABILITY_DESCRIPTIONS

    # ─── Classification Map ──────────────────────
    action_classes: dict[str, str] = ACTION_CLASSES

    # ─── Dependencies ────────────────────────────
    required_tools: list[str] = []
    optional_tools: list[str] = []
    required_integrations: list[str] = []

    # ─── Capabilities ────────────────────────────
    supports_cancellation: bool = True
    supports_idempotency: bool = False  # Desktop actions are not idempotent

    def __init__(
        self,
        surface: Any = None,
        llm: Any = None,
        *,
        agent_loop: Any = None,
        registry: Any = None,
        memory: ActionMemory | None = None,
        policy_bridge: PolicyBridge | None = None,
        trace_bridge: TraceBridge | None = None,
        recovery_bridge: RecoveryBridge | None = None,
    ) -> None:
        self._surface = surface
        self._llm = llm
        self._agent_loop = agent_loop
        self._registry = registry
        self._memory = memory or ActionMemory()

        # AI-OS bridges
        self._policy_bridge = policy_bridge or PolicyBridge()
        self._trace_bridge = trace_bridge or TraceBridge()
        self._recovery_bridge = recovery_bridge or RecoveryBridge()

        # Safety subsystems (v0.11.0)
        self._rate_governor = ActionRateGovernor()
        self._latency_budget = LatencyBudget()
        self._cost_tracker = CostTracker()

        # B38: Runtime execution hardening (v0.18.0)
        from deskaoy.runtime.types import (
            WINDOWS_CAPABILITIES,
            AdapterCapabilities,
            RuntimeResourceBudget,
        )
        self._capabilities: AdapterCapabilities | None = WINDOWS_CAPABILITIES if surface else None
        self._resource_budget = RuntimeResourceBudget()
        self._current_attempt = None

        # Safety subsystems (v0.13.0 — det-acp adoption)
        self._session_budget_tracker = SessionBudgetTracker()
        self._policy_evolution = PolicyEvolutionEngine()
        self._evidence_ledger: EvidenceLedger | None = None
        self._session_budget: SessionBudget | None = None

        # Storage resolver for checkpoint paths
        try:
            self._storage_resolver = StorageResolver()
        except Exception:
            self._storage_resolver = None

        # Compensation engine (v0.14.0 — det-acp rollback pattern)
        self._compensation = CompensationEngine(
            surface=surface,
            ledger=None,  # Set during configure_session
        )

        # Scheduled routines (v0.15.0)
        self._routine_scheduler = RoutineScheduler()

        # SKILL.md loader (v0.15.0)
        self._skill_loader = SkillLoader()

        # Fact extraction (v0.15.0)
        self._fact_store = FactStore()
        self._fact_extractor = FactExtractor()

        # Action parameter validation (v0.16.0)
        # (stateless — validate_action is a module-level function)

        # Resource tracker (v0.16.0)
        self._resource_tracker = ResourceTracker()

        # Snapshot store (v0.32.0 — BATCH-24 Peekaboo)
        from deskaoy.cascade.snapshot_store import SnapshotStore as _SnapshotStore
        self._snapshot_store = _SnapshotStore()

    # ─── Clipboard (BATCH-28) ────────────────────────────────────

    async def read_clipboard(self) -> str:
        """Read the system clipboard text via the surface adapter."""
        if self._surface is None:
            raise RuntimeError("No surface adapter configured")
        return await self._surface.read_clipboard()

    async def write_clipboard(self, text: str) -> None:
        """Write text to the system clipboard via the surface adapter."""
        if self._surface is None:
            raise RuntimeError("No surface adapter configured")
        await self._surface.write_clipboard(text)

    async def paste(self) -> ActionResult:
        """Send Ctrl+V to paste clipboard contents via the surface adapter."""
        if self._surface is None:
            return ActionResult(ok=False, data={"error": "No surface adapter configured"})
        return await self._surface.paste()

    # ─── Set Value / Perform Action (BATCH-28) ──────────────────

    async def set_value(self, target: str, value: str, *, dry_run: bool = False) -> ActionResult:
        """Set a value on a target element using UIA ValuePattern first.

        Falls back to click+type when ValuePattern is unavailable.
        This is a convenience facade over invoke_element(target, 'set_value', value=value).

        Args:
            target: Element identifier (name, auto:id, or coordinates).
            value: Value to set.
            dry_run: If True, return predicted result without executing.

        Returns:
            ActionResult with pattern_used metadata.
        """
        if self._surface is None:
            return ActionResult(ok=False, data={"error": "No surface adapter configured"})
        if dry_run:
            return ActionResult(
                ok=True,
                data={"action": "set_value", "target": target, "value": value, "dry_run": True},
            )
        return await self._surface.invoke_element(target, action="set_value", value=value)

    async def perform_action(
        self, target: str, action: str, *, value: str = "", dry_run: bool = False, **kwargs: Any,
    ) -> ActionResult:
        """Perform a named accessibility action on a target element.

        Supported actions: invoke, toggle, expand, collapse, select,
        scroll_into_view, focus, set_value, get_value.

        Uses action-first: tries UIA pattern first, falls back to pyautogui.

        Args:
            target: Element identifier (name, auto:id, or coordinates).
            action: Named action to perform.
            value: Optional value parameter (for set_value).
            dry_run: If True, return predicted result without executing.
            **kwargs: Additional arguments forwarded to invoke_element.

        Returns:
            ActionResult with pattern_used metadata.
        """
        if self._surface is None:
            return ActionResult(ok=False, data={"error": "No surface adapter configured"})
        if dry_run:
            return ActionResult(
                ok=True,
                data={"action": "perform_action", "target": target, "name": action, "dry_run": True},
            )
        return await self._surface.invoke_element(target, action=action, value=value, **kwargs)

    # ─── Snapshot Store (v0.32.0) ─────────────────

    @property
    def snapshot_store(self):
        """Persistent snapshot store for UI element snapshots."""
        return self._snapshot_store

    # ─── Desktop UI Services (v0.34.0 — BATCH-26) ──────────────────

    @property
    def menu(self):
        """MenuService — Start Menu + app menu bar interaction."""
        if not hasattr(self, '_menu_service') or self._menu_service is None:
            from deskaoy.services.menu_service import MenuService
            self._menu_service = MenuService()
        return self._menu_service

    @property
    def taskbar(self):
        """TaskbarService — Taskbar buttons + system tray."""
        if not hasattr(self, '_taskbar_service') or self._taskbar_service is None:
            from deskaoy.services.taskbar_service import TaskbarService
            self._taskbar_service = TaskbarService()
        return self._taskbar_service

    @property
    def dialog(self):
        """DialogService — System dialog driving."""
        if not hasattr(self, '_dialog_service') or self._dialog_service is None:
            from deskaoy.services.dialog_service import DialogService
            self._dialog_service = DialogService()
        return self._dialog_service

    @property
    def desktop(self):
        """DesktopService — Virtual desktop management."""
        if not hasattr(self, '_desktop_service') or self._desktop_service is None:
            from deskaoy.services.desktop_service import DesktopService
            self._desktop_service = DesktopService()
        return self._desktop_service

    # ─── Agent Protocol: execute ──────────────────

    async def execute(
        self, goal: AgentGoal, context: AgentContext
    ) -> AgentResult:
        """Execute a desktop automation goal."""
        start = time.monotonic()

        # ── Hooks: emit before_execute ──
        await global_hooks.emit(HookName.ON_BEFORE_EXECUTE, HookContext(
            command=goal.capability, args=goal.params, started_at=start,
        ))

        # Validate capability
        if goal.capability not in CAPABILITIES:
            return self._unknown_capability_result(context, goal)

        cap_meta = CAPABILITIES[goal.capability]

        # ── Wire 5a: Session budget pre-check (det-acp pattern) ──
        if self._session_budget is not None:
            should_stop, reason = self._session_budget_tracker.should_terminate(self._session_budget)
            if should_stop:
                return AgentResult(
                    execution_id=context.execution_id,
                    status=ResultStatus.RATE_LIMITED,
                    summary=f"Session terminated: {reason}",
                    data={"session_budget": self._session_budget_tracker.snapshot(self._session_budget)},
                    confidence=Confidence(score=0.0, reason=reason),
                    issues=[Issue(
                        severity=IssueSeverity.ERROR,
                        code=ErrorCode.RATE_LIMITED,
                        message=reason,
                        retry_possible=False,
                    )],
                )
            # Append to evidence ledger
            if self._evidence_ledger is not None:
                try:
                    await self._evidence_ledger.append(
                        context.execution_id, "action:evaluate",
                        {"capability": goal.capability, "params": dict(goal.params)},
                    )
                except Exception as exc:
                    logger.warning("Evidence ledger append failed: %s", exc)

        # Dry run
        if context.dry_run:
            return self._dry_run_result(context, goal, cap_meta)

        # Cancellation check
        try:
            context.cancellation_token.check()
        except OperationCancelled:
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.CANCELLED,
                summary="Cancelled before execution",
                data={},
                confidence=Confidence(score=0.0, reason="Cancelled"),
            )

        # Route to handler
        try:
            if goal.capability == "automate":
                result = await self._execute_automate(goal, context, start)
            elif goal.capability == "orchestrate":
                result = await self._execute_orchestrate(goal, context, start)
            else:
                result = await self._execute_single_action(goal, context, start, cap_meta)

            # ── Wire 5b: Record to session budget (det-acp pattern) ──
            if self._session_budget is not None:
                allowed = result.status == ResultStatus.SUCCESS
                duration = (time.monotonic() - start) * 1000
                cost = cap_meta.get("cost_estimate", 0.0)
                self._session_budget_tracker.record_action(
                    self._session_budget, allowed=allowed, duration_ms=duration, cost_usd=cost,
                )
                # Check escalation
                events = self._session_budget_tracker.check(self._session_budget)
                for ev in events:
                    logger.warning("Session budget event: %s = %s (limit: %s)",
                                   ev.threshold, ev.current_value, ev.limit_value)
                should_stop, reason = self._session_budget_tracker.should_terminate(self._session_budget)
                if should_stop:
                    logger.error("Session terminated: %s", reason)
                    result = AgentResult(
                        execution_id=context.execution_id,
                        status=ResultStatus.RATE_LIMITED,
                        summary=f"Session terminated: {reason}",
                        data={"session_budget": self._session_budget_tracker.snapshot(self._session_budget)},
                        confidence=Confidence(score=0.0, reason=reason),
                        issues=[Issue(
                            severity=IssueSeverity.ERROR,
                            code=ErrorCode.RATE_LIMITED,
                            message=reason,
                            retry_possible=False,
                        )],
                    )

            # ── Wire 5c: Append to evidence ledger (det-acp pattern) ──
            if self._evidence_ledger is not None:
                try:
                    await self._evidence_ledger.append(
                        context.execution_id,
                        "action:result",
                        {
                            "capability": goal.capability,
                            "ok": result.status == ResultStatus.SUCCESS,
                            "duration_ms": (time.monotonic() - start) * 1000,
                            "confidence": result.confidence.score,
                        },
                    )
                except Exception as exc:
                    logger.warning("Evidence ledger append failed: %s", exc)
        except OperationCancelled:
            result = AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.CANCELLED,
                summary="Cancelled during execution",
                data={},
                confidence=Confidence(score=0.0, reason="Cancelled mid-execution"),
            )
        except TimeoutError:
            result = AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.RATE_LIMITED,
                summary=f"Execution timed out after {context.timeout_seconds}s",
                data={},
                confidence=Confidence(score=0.0, reason="Timeout"),
                issues=[Issue(
                    severity=IssueSeverity.ERROR,
                    code=ErrorCode.TIMEOUT,
                    message=f"Desktop action exceeded {context.timeout_seconds}s timeout",
                    retry_possible=True,
                )],
            )
        except Exception as exc:
            logger.exception("DesktopAgent.execute failed")
            # Classify internal errors into richer status codes
            status = ResultStatus.FAILURE
            error_code = ErrorCode.INTERNAL_ERROR
            if isinstance(exc, (ConnectionError, OSError)):
                status = ResultStatus.RETRYABLE
                error_code = ErrorCode.NETWORK_ERROR
            result = AgentResult(
                execution_id=context.execution_id,
                status=status,
                summary=f"Internal error: {exc}",
                data={},
                confidence=Confidence(score=0.0, reason="Internal error"),
                issues=[Issue(
                    severity=IssueSeverity.ERROR,
                    code=error_code,
                    message=str(exc),
                    retry_possible=status == ResultStatus.RETRYABLE,
                )],
            )

        # ── Hooks: emit after_execute ──
        await global_hooks.emit(HookName.ON_AFTER_EXECUTE, HookContext(
            command=goal.capability,
            args=goal.params,
            started_at=start,
            finished_at=time.monotonic(),
            extra={"ok": result.status == ResultStatus.SUCCESS},
        ))

        return result

    # ─── Agent Protocol: estimate ─────────────────

    async def estimate(
        self, goal: AgentGoal, context: AgentContext
    ) -> AgentEstimate:
        """Estimate cost, latency, and confidence before execution."""
        cap_meta = CAPABILITIES.get(goal.capability)
        if cap_meta is None:
            return AgentEstimate(
                cost_usd=0.0,
                latency_ms=0,
                confidence=Confidence(score=0.0, reason=f"Unknown capability: {goal.capability}"),
                requires_auth=False,
                can_execute=False,
                refusal_reason=f"Unknown capability: {goal.capability}",
            )

        has_surface = self._surface is not None
        can_execute = has_surface

        # Multi-step automate costs more (LLM tokens + multiple actions)
        is_automate = goal.capability == "automate"
        base_cost = cap_meta["cost_estimate"]
        cost = base_cost * 10 if is_automate else base_cost
        latency = 5000 if is_automate else 500

        return AgentEstimate(
            cost_usd=cost,
            latency_ms=latency,
            confidence=Confidence(
                score=0.7 if has_surface else 0.0,
                reason="Surface adapter available" if has_surface else "No surface adapter configured",
            ),
            requires_auth=False,
            can_execute=can_execute,
            refusal_reason="" if can_execute else "No surface adapter configured",
            provider_healthy=has_surface,
        )

    # ─── Agent Protocol: undo ─────────────────────

    async def undo(self, execution_id: str, snapshot: Snapshot) -> UndoResult:
        """Reverse a previous execution using the compensation engine.

        Builds a LIFO compensation plan from registered actions and
        executes it best-effort against the surface adapter.
        Every rollback step is recorded in the evidence ledger.
        """
        plan = self._compensation.build_plan(execution_id)
        if not plan.steps:
            return UndoResult(
                execution_id=execution_id,
                success=False,
                summary="No undo information for this execution",
                manual_instructions="This action was not registered for rollback. "
                                   "Please manually reverse the change.",
            )

        report = await self._compensation.execute_plan(plan)

        # Build manual instructions for failed/skipped steps
        failed_steps = [r for r in report.results if not r.success]
        manual_parts = []
        for step in failed_steps:
            manual_parts.append(f"- {step.action} ({step.target}): {step.description}")

        return UndoResult(
            execution_id=execution_id,
            success=report.failed == 0,
            summary=f"Rolled back {report.succeeded}/{report.total_steps} steps "
                    f"({report.skipped} skipped, {report.failed} failed)",
            manual_instructions="\n".join(manual_parts) if manual_parts else "",
            metadata={
                "plan_id": report.plan_id,
                "succeeded": report.succeeded,
                "failed": report.failed,
                "skipped": report.skipped,
            },
        )

    # ─── Agent Protocol: compensate ───────────────

    async def compensate(self, execution_id: str, snapshot: Snapshot) -> UndoResult:
        """Compensate for a desktop action using the compensation engine.

        Same as undo — builds and executes a LIFO compensation plan.
        If no registered actions exist, falls back to guidance.
        """
        # Same engine as undo — the compensation plan handles it
        return await self.undo(execution_id, snapshot)

    async def build_undo_plan(self, execution_id: str) -> CompensationPlan:
        """Preview what undo would do without executing it.

        Returns the compensation plan showing which actions would be
        reversed and in what order. Useful for displaying a preview
        to the user before confirming rollback.
        """
        return self._compensation.build_plan(execution_id)

    # ─── Internal: single action execution ────────

    async def _execute_single_action(
        self,
        goal: AgentGoal,
        context: AgentContext,
        start: float,
        cap_meta: dict,
    ) -> AgentResult:
        """Execute a single SurfaceAdapter method."""
        if self._surface is None:
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.CONFIG_ERROR,
                summary="No surface adapter configured",
                data={},
                confidence=Confidence(score=0.0, reason="No surface adapter"),
                issues=[Issue(
                    severity=IssueSeverity.ERROR,
                    code=ErrorCode.DEPENDENCY_MISSING,
                    message="Surface adapter not configured. Initialize DesktopAgent with a surface.",
                )],
            )

        method_name = cap_meta["method"]
        assert method_name is not None, f"Single action {goal.capability} has no adapter method"

        # ── B38: Runtime Preflight Gate ──
        # The canonical preflight runs BEFORE any other checks, producing
        # a PreflightResult with fingerprint. If blocked, execution stops here.
        from deskaoy.runtime import RuntimeAttempt, RuntimeAttemptState, RuntimePreflight
        from deskaoy.runtime.types import (
            RuntimeExecutionReceipt,
            make_truth_message,
        )

        attempt = RuntimeAttempt(context.execution_id)
        preflight_svc = RuntimePreflight(self)
        preflight_result = await preflight_svc.run(
            goal, context,
            policy_decision=None,  # Will be set after policy check
            capabilities=getattr(self, '_capabilities', None),
            resource_budget=getattr(self, '_resource_budget', None),
        )
        attempt.set_preflight_result(preflight_result)

        if not preflight_result.passed:
            attempt.transition(RuntimeAttemptState.BLOCKED)
            receipt = RuntimeExecutionReceipt(
                execution_id=context.execution_id,
                attempt_id=attempt.attempt_id,
                attempt_state=attempt.state,
                truth_message=make_truth_message(attempt.state),
                runtime_execution_performed=False,
                simulated=False,
                dry_run=getattr(context, 'dry_run', False),
                side_effects_performed=False,
                preflight_passed=False,
                preflight_fingerprint=preflight_result.fingerprint,
                obligations_checked=[str(o) for o in preflight_result.obligations_required],
                obligations_blocked=[],
            )
            receipt.freeze()
            attempt.set_receipt(receipt)
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.FAILURE,
                summary=f"Preflight blocked: {preflight_result.blocked_reason}",
                data={"receipt": receipt.to_dict(), "preflight": preflight_result.to_dict()},
                confidence=Confidence(score=0.0, reason="Preflight failed"),
                issues=[Issue(
                    severity=IssueSeverity.ERROR,
                    code=ErrorCode.PERMISSION_DENIED,
                    message=preflight_result.blocked_reason,
                )],
            )

        # Preflight passed — transition
        attempt.transition(RuntimeAttemptState.PREFLIGHT_PASSED)
        # Store attempt for later receipt generation
        self._current_attempt = attempt

        adapter_method = getattr(self._surface, method_name, None)
        if adapter_method is None:
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.FAILURE,
                summary=f"Surface adapter missing method: {method_name}",
                data={},
                confidence=Confidence(score=0.0, reason="Missing adapter method"),
                issues=[Issue(
                    severity=IssueSeverity.ERROR,
                    code=ErrorCode.DEPENDENCY_MISSING,
                    message=f"Surface adapter does not implement {method_name}",
                )],
            )

        # ── Wire 0: Rate limit check ──
        if not self._rate_governor.check(goal.capability):
            wait = self._rate_governor.wait_if_needed(goal.capability)
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.RATE_LIMITED,
                summary=f"Rate limited on '{goal.capability}' — wait {wait:.1f}s",
                data={},
                confidence=Confidence(score=0.0, reason="Rate limited"),
                issues=[Issue(
                    severity=IssueSeverity.WARNING,
                    code=ErrorCode.RATE_LIMITED,
                    message=f"Rate limit exceeded for '{goal.capability}'. Retry after {wait:.1f}s.",
                    retry_possible=True,
                )],
            )

        # ── Wire 1: Policy preflight ──
        policy_decision = await self._policy_bridge.preflight(
            goal.capability, context=getattr(context, "execution_id", "")
        )
        # A policy override from self-evolution. Only ALLOW_ONCE sets this;
        # execution below proceeds iff the *final* policy_decision is non-DENY
        # OR an explicit override was granted. Denial must never fall through.
        policy_override_allowed = False
        if policy_decision.effect == PolicyEffect.DENY:
            # ── Wire 1b: Policy self-evolution (det-acp pattern) ──
            suggestion = self._policy_evolution.suggest(goal.capability, policy_decision.reason)
            if suggestion is not None:
                result = await self._policy_evolution.evolve(suggestion)
                if result.decision == EvolutionDecision.ADD_TO_POLICY:
                    logger.info("Policy evolved: allowing '%s' (added to policy)", goal.capability)
                    # Re-check policy after evolution
                    policy_decision = await self._policy_bridge.preflight(
                        goal.capability, context=getattr(context, "execution_id", "")
                    )
                    if policy_decision.effect == PolicyEffect.DENY:
                        # Still denied after evolution — hard stop.
                        # (Previously fell through to execution via an empty
                        # `pass`; that was a P0 safety fallthrough.)
                        return self._policy_denied_result(context, policy_decision)
                    # Evolution worked — re-check allowed; fall through to execution.
                elif result.decision == EvolutionDecision.ALLOW_ONCE:
                    logger.info("Policy evolution: one-time override for '%s'", goal.capability)
                    policy_override_allowed = True
                else:
                    # User chose to keep the denial — hard stop.
                    return self._policy_denied_result(context, policy_decision)
            else:
                # No suggestion possible — hard deny
                return self._policy_denied_result(context, policy_decision)
        if policy_decision.effect == PolicyEffect.ASK:
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.NEEDS_REVIEW,
                summary="Action requires user approval",
                data={"policy_decision_id": policy_decision.policy_decision_id},
                confidence=Confidence(score=0.0, reason="Pending approval"),
            )
        if policy_decision.effect == PolicyEffect.ALLOW_DRY_RUN_ONLY:
            return self._dry_run_result(context, goal, CAPABILITIES.get(goal.capability, {}))

        # ── Defense-in-depth: invariant gate before any execution ──
        # Every DENY path above must hard-return; this guard ensures that even
        # if a future edit accidentally lets a DENY fall through, execution is
        # still blocked. The only way past a DENY is an explicit ALLOW_ONCE
        # override granted by policy self-evolution.
        if policy_decision.effect == PolicyEffect.DENY and not policy_override_allowed:
            return self._policy_denied_result(context, policy_decision)

        # ── Wire 8: Action parameter validation (OSWorld pattern) ──
        validation = validate_action(goal.capability, dict(goal.params))
        if not validation.valid:
            errors = "; ".join(i.message for i in validation.errors)
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.FAILURE,
                summary=f"Invalid parameters: {errors}",
                data={"validation_issues": [i.__dict__ for i in validation.issues]},
                confidence=Confidence(score=0.0, reason="Invalid parameters"),
                issues=[Issue(
                    severity=IssueSeverity.ERROR,
                    code=ErrorCode.VALIDATION_ERROR,
                    message=errors,
                )],
            )
        params = validation.sanitized_params

        # ── B38: TOCTOU check — verify fingerprint hasn't changed ──
        preflight_svc_verify = RuntimePreflight(self)
        current_fingerprint = preflight_svc_verify._compute_fingerprint(
            attempt.preflight_result.checks,
            getattr(self, '_capabilities', None),
            None,
        )
        if (attempt.preflight_result
                and current_fingerprint != attempt.preflight_result.fingerprint):
            attempt.transition(RuntimeAttemptState.BLOCKED)
            receipt = RuntimeExecutionReceipt(
                execution_id=context.execution_id,
                attempt_id=attempt.attempt_id,
                attempt_state=attempt.state,
                truth_message="Execution blocked: preflight fingerprint stale (TOCTOU detected).",
                runtime_execution_performed=False,
                simulated=False,
                dry_run=getattr(context, 'dry_run', False),
                side_effects_performed=False,
                preflight_passed=False,
                preflight_fingerprint=attempt.preflight_result.fingerprint,
                obligations_checked=[],
                obligations_blocked=[],
            )
            receipt.freeze()
            attempt.set_receipt(receipt)
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.FAILURE,
                summary="Preflight fingerprint stale — state changed between preflight and execution",
                data={"receipt": receipt.to_dict()},
                confidence=Confidence(score=0.0, reason="TOCTOU detected"),
                issues=[Issue(
                    severity=IssueSeverity.ERROR,
                    code=ErrorCode.PERMISSION_DENIED,
                    message="preflight_stale: state changed after preflight check",
                )],
            )

        # Preflight fingerprint verified — transition to RUNNING
        attempt.transition(RuntimeAttemptState.RUNNING)

        # Capture before-state for mutation tracking
        before_state = await self._capture_surface_state()
        context.cancellation_token.check()

        # Execute the adapter method (with timeout → receipt).
        # NOTE: dispatch uses `validation.sanitized_params`, NOT raw `goal.params`.
        # The sanitized params have been type-coerced, defaults applied, and
        # disallowed keys stripped. Re-reading goal.params here was a P0 safety
        # regression (validated/sanitized values were discarded before dispatch).
        try:
            action_result: ActionResult = await asyncio.wait_for(
                adapter_method(**params),
                timeout=context.timeout_seconds,
            )
        except TimeoutError:
            # ── B38: Timeout receipt ──
            attempt.transition(RuntimeAttemptState.TIMED_OUT)
            receipt = RuntimeExecutionReceipt(
                execution_id=context.execution_id,
                attempt_id=attempt.attempt_id,
                attempt_state=attempt.state,
                truth_message=make_truth_message(attempt.state),
                runtime_execution_performed=False,
                simulated=False,
                dry_run=getattr(context, 'dry_run', False),
                side_effects_performed=False,
                preflight_passed=True,
                preflight_fingerprint=attempt.preflight_result.fingerprint if attempt.preflight_result else "",
                obligations_checked=[str(o) for o in (attempt.preflight_result.obligations_required if attempt.preflight_result else [])],
                obligations_blocked=[],
                resource_budget=getattr(self, '_resource_budget', None),
            )
            receipt.freeze()
            attempt.set_receipt(receipt)
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.FAILURE,
                summary=f"Action timed out after {context.timeout_seconds}s",
                data={"receipt": receipt.to_dict()},
                confidence=Confidence(score=0.0, reason="Timeout"),
                issues=[Issue(
                    severity=IssueSeverity.ERROR,
                    code=ErrorCode.TIMEOUT,
                    message=f"Adapter method '{method_name}' exceeded {context.timeout_seconds}s timeout",
                )],
            )
        duration_ms = (time.monotonic() - start) * 1000

        # Capture after-state
        after_state = await self._capture_surface_state()
        context.cancellation_token.check()

        # ── Wire 4: Post-action grounding verification (LangExtract pattern A) ──
        post_snapshot = after_state.get("ax_snapshot")
        target_ref = str(params.get("target", ""))
        grounding = verify_grounding(
            target_ref=target_ref if target_ref.startswith("e") else "",
            target_text=target_ref,
            target_bounds=None,
            post_snapshot=post_snapshot,
        )
        # Attach grounding to action result data
        if isinstance(action_result.data, dict):
            action_result.data["grounding"] = grounding.to_dict()
        elif action_result.data is None:
            action_result.data = {"grounding": grounding.to_dict()}

        # Build mutation record for non-read-only actions.
        # Always record mutations for sensitive/recoverable/etc. actions
        # even if the surface state snapshot looks identical (e.g. mock adapter).
        mutations = []
        action_class = cap_meta["action_class"]
        if action_class != "read_only":
            restore = self._restore_method_for_class(action_class)
            mutations.append(MutationRecord(
                resource_type="desktop_surface",
                resource_id=before_state.get("focus", "unknown"),
                operation=goal.capability,
                before_state=before_state,
                after_state=after_state,
                restore_method=restore,
            ))

        # ── Wire 6: Register compensation strategy (det-acp rollback pattern) ──
        self._compensation.register(
            execution_id=context.execution_id,
            action=goal.capability,
            target=str(params.get("target", "")),
            before_state=before_state,
            params=params,
        )

        # ── Wire 7: Fact extraction (v0.15.0 — Pocket Agent pattern) ──
        extracted_facts = self._fact_extractor.extract_from_result(
            action=goal.capability,
            target=str(params.get("target", "")),
            result_value=str(action_result.data) if isinstance(action_result.data, dict) else "",
            params=params,
        )
        for fact in extracted_facts:
            self._fact_store.save_fact(fact)

        # Build confidence from action result
        confidence = self._confidence_from_action(action_result)

        # Record to action memory
        await self._record_to_memory(goal, action_result, context)

        # ── Wire 0b: Record rate + latency ──
        self._rate_governor.record(goal.capability)
        latency_measurement = self._latency_budget.record(goal.capability, duration_ms)
        if latency_measurement.exceeded_p99:
            logger.error(
                "Action '%s' exceeded p99 budget: %.0fms > %.0fms",
                goal.capability, duration_ms, latency_measurement.budget_p99,
            )
        elif latency_measurement.exceeded_p95:
            logger.warning(
                "Action '%s' exceeded p95 budget: %.0fms > %.0fms",
                goal.capability, duration_ms, latency_measurement.budget_p95,
            )

        # ── Wire 2: Trace span ──
        await self._trace_bridge.emit(ActionSpan(
            action=goal.capability,
            duration_ms=duration_ms,
            ok=action_result.ok,
            confidence=confidence.score,
            trace_id=context.execution_id,
            surface_id=getattr(self._surface, "name", "unknown"),
        ))

        status = ResultStatus.SUCCESS if action_result.ok else ResultStatus.FAILURE
        summary = self._summarize_action(goal, action_result, duration_ms)

        # ── Wire E: Retry with backoff on transient failures ──
        if not action_result.ok:
            error_code = str(action_result.error.code) if action_result.error else ""
            if await self._recovery_bridge.wait_and_retry(goal.capability, error_code):
                # Retry the action
                try:
                    action_result = await asyncio.wait_for(
                        adapter_method(**params),
                        timeout=context.timeout_seconds,
                    )
                    duration_ms = (time.monotonic() - start) * 1000
                    status = ResultStatus.SUCCESS if action_result.ok else ResultStatus.FAILURE
                    summary = self._summarize_action(goal, action_result, duration_ms) + " (retried)"
                    self._recovery_bridge.circuit_breaker.record_success()
                except Exception as retry_exc:
                    self._recovery_bridge.circuit_breaker.record_failure()
                    summary = f"{summary} — retry failed: {retry_exc}"

        # ── Wire 3: Result mapper ──
        aios_mapped = map_action_result(
            action_result, dry_run=False
        )

        # ── B38: Generate completion/failure receipt ──
        has_side_effects = (
            status == ResultStatus.SUCCESS
            and cap_meta.get("action_class", "read_only") != "read_only"
        )
        terminal_state = (
            RuntimeAttemptState.COMPLETED
            if status == ResultStatus.SUCCESS
            else RuntimeAttemptState.FAILED
        )
        attempt.transition(terminal_state)
        receipt = RuntimeExecutionReceipt(
            execution_id=context.execution_id,
            attempt_id=attempt.attempt_id,
            attempt_state=attempt.state,
            truth_message=make_truth_message(
                attempt.state,
                dry_run=getattr(context, 'dry_run', False),
                simulated=False,
                side_effects=has_side_effects,
            ),
            runtime_execution_performed=True,
            simulated=False,
            dry_run=getattr(context, 'dry_run', False),
            side_effects_performed=has_side_effects,
            preflight_passed=True,
            preflight_fingerprint=attempt.preflight_result.fingerprint if attempt.preflight_result else "",
            obligations_checked=[str(o) for o in (attempt.preflight_result.obligations_required if attempt.preflight_result else [])],
            obligations_blocked=[],
            resource_budget=getattr(self, '_resource_budget', None),
        )
        receipt.freeze()
        attempt.set_receipt(receipt)

        # Merge receipt into result data
        result_data = (
            action_result.data
            if isinstance(action_result.data, dict)
            else {"raw": str(action_result.data)}
        )
        result_data["receipt"] = receipt.to_dict()

        return AgentResult(
            execution_id=context.execution_id,
            status=status,
            summary=summary,
            data=result_data,
            mutations=mutations,
            confidence=confidence,
            metadata={
                "duration_ms": duration_ms,
                "provider": "deskaoy",
                "action": goal.capability,
                "aios_mapped": aios_mapped.to_dict(),
            },
        )

    # ─── Internal: multi-app orchestration ────────

    async def _execute_orchestrate(
        self,
        goal: AgentGoal,
        context: AgentContext,
        start: float,
    ) -> AgentResult:
        """Execute a multi-app orchestration using HostAgent + DAG."""
        instruction = goal.params.get("instruction", goal.params.get("query", ""))
        if not instruction:
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.FAILURE,
                summary="No instruction provided for orchestration",
                data={},
                confidence=Confidence(score=0.0, reason="Missing instruction"),
                issues=[Issue(
                    severity=IssueSeverity.ERROR,
                    code=ErrorCode.VALIDATION_ERROR,
                    message="The 'orchestrate' capability requires an 'instruction' parameter.",
                )],
            )

        from deskaoy.orchestration.host_agent import HostAgent

        def surface_factory(app_name: str):
            """Create a scoped surface adapter for the given app."""
            if self._surface is None:
                return None
            # Return the shared surface for now — window scoping is handled
            # by the AppAgent at the OS level (win32gui focus)
            return self._surface

        host = HostAgent(
            llm=self._llm,
            surface_factory=surface_factory,
        )
        orch_result = await host.orchestrate(instruction)
        duration_ms = (time.monotonic() - start) * 1000

        status = ResultStatus.SUCCESS if orch_result.ok else ResultStatus.PARTIAL
        return AgentResult(
            execution_id=context.execution_id,
            status=status,
            summary=f"Orchestrated '{instruction[:50]}': {len(orch_result.subtasks)} subtasks, "
                    f"{'all succeeded' if orch_result.ok else 'some failed'}",
            data=orch_result.to_dict(),
            confidence=Confidence(
                score=1.0 if orch_result.ok else 0.5,
                reason=f"{len([s for s in orch_result.subtasks if s.ok])}/{len(orch_result.subtasks)} subtasks succeeded",
            ),
            metadata={
                "duration_ms": duration_ms,
                "provider": "deskaoy",
                "action": "orchestrate",
                "decomposition_source": orch_result.decomposition_source,
            },
        )

    # ─── Internal: multi-step automation ──────────

    async def _execute_automate(
        self,
        goal: AgentGoal,
        context: AgentContext,
        start: float,
    ) -> AgentResult:
        """Execute a multi-step automation goal using AgentLoop."""
        instruction = goal.params.get("instruction", goal.params.get("query", ""))
        if not instruction:
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.FAILURE,
                summary="No instruction provided for automation goal",
                data={},
                confidence=Confidence(score=0.0, reason="Missing instruction"),
                issues=[Issue(
                    severity=IssueSeverity.ERROR,
                    code=ErrorCode.VALIDATION_ERROR,
                    message="The 'automate' capability requires an 'instruction' parameter.",
                )],
            )

        # ── Cost budget check ──
        if self._cost_tracker.budget_exceeded:
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.FAILURE,
                summary=f"LLM cost budget exceeded (${self._cost_tracker.total_cost:.4f}/${self._cost_tracker.budget_usd:.2f})",
                data={"cost_summary": self._cost_tracker.summary},
                confidence=Confidence(score=0.0, reason="Budget exhausted"),
                issues=[Issue(
                    severity=IssueSeverity.ERROR,
                    code=ErrorCode.BUDGET_EXCEEDED,
                    message=f"LLM cost budget of ${self._cost_tracker.budget_usd:.2f} exceeded.",
                    retry_possible=False,
                )],
            )

        # ── Pre-flight validation (LangExtract pattern B) ──
        validation_report = validate_instruction(
            instruction, agent=self, level=ValidationLevel.WARNING,
        )
        if validation_report.has_errors:
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.FAILURE,
                summary="Instruction validation failed",
                data={"validation": validation_report.to_dict()},
                confidence=Confidence(score=0.0, reason="Invalid instruction"),
                issues=[Issue(
                    severity=IssueSeverity.WARNING,
                    code=ErrorCode.VALIDATION_ERROR,
                    message=issue.message,
                ) for issue in validation_report.issues],
            )

        # ── Pipeline fast-path: zero-LLM for known workflows ──
        pipeline_result = await self._try_pipeline(instruction, goal.params)
        if pipeline_result is not None:
            duration_ms = (time.monotonic() - start) * 1000
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.SUCCESS if pipeline_result.ok else ResultStatus.FAILURE,
                summary=f"Pipeline: {'ok' if pipeline_result.ok else 'failed'}",
                data=pipeline_result.data if isinstance(pipeline_result.data, dict) else {},
                confidence=Confidence(
                    score=0.95 if pipeline_result.ok else 0.1,
                    reason="Deterministic pipeline (zero LLM cost)" if pipeline_result.ok else "Pipeline failed",
                ),
                metadata={"duration_ms": duration_ms, "provider": "pipeline"},
            )

        if self._agent_loop is None:
            # Fall back to single-step if no loop configured
            if self._llm is not None and self._surface is not None:
                return await self._execute_automate_with_llm(goal, context, start, instruction)
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.FAILURE,
                summary="No agent loop or LLM configured for multi-step automation",
                data={},
                confidence=Confidence(score=0.0, reason="No agent loop"),
                issues=[Issue(
                    severity=IssueSeverity.ERROR,
                    code=ErrorCode.DEPENDENCY_MISSING,
                    message="Agent loop not configured. Provide agent_loop or llm + surface.",
                )],
            )

        # Capture before-state
        before_state = await self._capture_surface_state()

        # Run the agent loop
        loop_result = await asyncio.wait_for(
            self._agent_loop.run(instruction),
            timeout=context.timeout_seconds,
        )
        duration_ms = (time.monotonic() - start) * 1000

        # Capture after-state
        after_state = await self._capture_surface_state()

        # Map loop completion reason to ResultStatus
        reason_map = {
            "success": ResultStatus.SUCCESS,
            "loop_detected": ResultStatus.PARTIAL,
            "max_steps": ResultStatus.PARTIAL,
            "abort": ResultStatus.CANCELLED,
        }
        status = reason_map.get(loop_result.completion_reason, ResultStatus.PARTIAL)

        # Build mutation
        mutations = []
        if before_state != after_state:
            mutations.append(MutationRecord(
                resource_type="desktop_surface",
                resource_id=before_state.get("focus", "unknown"),
                operation="automate",
                before_state=before_state,
                after_state=after_state,
                restore_method=RestoreMethod.RESTORE_STATE,
            ))

        if mutations:
            self._execution_snapshots[context.execution_id] = mutations

        # Confidence from loop result quality
        success_steps = sum(1 for s in loop_result.steps if s.error is None)
        total_steps = len(loop_result.steps) or 1
        conf_score = min(success_steps / total_steps, 1.0)

        summary = (
            f"Automated '{instruction[:50]}': "
            f"{loop_result.total_steps} steps, {loop_result.completion_reason}"
        )

        # Extract learnings from the execution
        learnings = self._extract_learnings(loop_result, context)

        # ── Wire 2: Trace span for automate ──
        await self._trace_bridge.emit(ActionSpan(
            action="automate",
            duration_ms=duration_ms,
            ok=status == ResultStatus.SUCCESS,
            confidence=conf_score,
            trace_id=context.execution_id,
            surface_id=getattr(self._surface, "name", "unknown"),
        ))

        # ── Wire 4: Recovery bridge — emit failure evidence if steps exhausted ──
        if status != ResultStatus.SUCCESS:
            await self._recovery_bridge.emit_failure_evidence(
                action="automate",
                target=instruction[:50],
                error_message=loop_result.completion_reason,
                attempt_count=total_steps,
                trace_id=context.execution_id,
            )

        return AgentResult(
            execution_id=context.execution_id,
            status=status,
            summary=summary,
            data={
                "steps": [
                    {
                        "step": s.step_number,
                        "action": s.action_name,
                        "ok": s.error is None,
                        "duration_ms": s.duration_ms,
                    }
                    for s in loop_result.steps
                ],
                "completion_reason": loop_result.completion_reason,
                "total_duration_ms": loop_result.total_duration_ms,
            },
            mutations=mutations,
            confidence=Confidence(
                score=conf_score,
                reason=f"{success_steps}/{total_steps} steps succeeded, "
                       f"reason={loop_result.completion_reason}",
                factors={
                    "total_steps": total_steps,
                    "success_steps": success_steps,
                    "loop_detections": loop_result.loop_detections,
                    "replan_count": loop_result.replan_count,
                },
            ),
            learnings=learnings,
            metadata={
                "duration_ms": duration_ms,
                "provider": "deskaoy",
                "action": "automate",
                "total_steps": total_steps,
                "aios_trace_spans": self._trace_bridge.span_count,
            },
        )

    async def _execute_automate_with_llm(
        self,
        goal: AgentGoal,
        context: AgentContext,
        start: float,
        instruction: str,
    ) -> AgentResult:
        """Simple single-step LLM-driven automation when no AgentLoop is configured."""
        # This is a fallback — create a minimal interaction
        before_state = await self._capture_surface_state()

        # Ask the LLM what action to take
        from deskaoy.agent.registry import ToolRegistry
        registry = self._registry or ToolRegistry()
        tool_api = registry.build_tool_api_description()

        # Inject facts and soul into prompt context (v0.15.0)
        context_parts = []
        facts_ctx = self._fact_store.facts_for_context()
        if facts_ctx:
            context_parts.append(facts_ctx)
        soul_ctx = self._fact_store.soul_for_context()
        if soul_ctx:
            context_parts.append(soul_ctx)

        context_block = "\n\n".join(context_parts) + "\n\n" if context_parts else ""

        prompt = (
            f"{context_block}"
            f"Instruction: {instruction}\n\n"
            f"{tool_api}\n\n"
            f"Respond with a JSON action: {{\"action\": \"...\", \"params\": {{...}}}}"
        )
        llm_response = await self._llm.propose_action(prompt)
        action_name = llm_response.get("action", "")
        action_params = llm_response.get("params", {})

        if not action_name:
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.FAILURE,
                summary="LLM did not propose an action",
                data={"llm_response": llm_response},
                confidence=Confidence(score=0.1, reason="No action proposed"),
            )

        # Dispatch the action
        tool = registry.get(action_name)
        if tool is None:
            return AgentResult(
                execution_id=context.execution_id,
                status=ResultStatus.FAILURE,
                summary=f"Unknown action: {action_name}",
                data={},
                confidence=Confidence(score=0.0, reason="Unknown action"),
                issues=[Issue(
                    severity=IssueSeverity.ERROR,
                    code=ErrorCode.VALIDATION_ERROR,
                    message=f"LLM proposed unknown action: {action_name}",
                )],
            )

        result = tool.handler(**action_params)
        if asyncio.iscoroutine(result):
            result = await result
        duration_ms = (time.monotonic() - start) * 1000

        after_state = await self._capture_surface_state()

        return AgentResult(
            execution_id=context.execution_id,
            status=ResultStatus.SUCCESS if result.ok else ResultStatus.FAILURE,
            summary=f"Executed {action_name}: {'ok' if result.ok else 'failed'}",
            data=result.data if isinstance(result.data, dict) else {"raw": str(result.data)},
            mutations=[MutationRecord(
                resource_type="desktop_surface",
                resource_id=before_state.get("focus", "unknown"),
                operation=action_name,
                before_state=before_state,
                after_state=after_state,
                restore_method=RestoreMethod.RESTORE_STATE,
            )] if before_state != after_state else [],
            confidence=Confidence(
                score=0.6,
                reason="Single-step LLM automation, no verification",
            ),
            metadata={"duration_ms": duration_ms, "provider": "deskaoy"},
        )

    # ─── Internal: helpers ────────────────────────

    async def _try_pipeline(self, instruction: str, params: dict) -> ActionResult | None:
        """Check for a deterministic pipeline match. Returns None if no match."""
        if self._surface is None:
            return None

        registry = _get_pipeline_registry()
        # Match against any surface type — the pipeline itself declares its constraint
        pipeline = registry.match(instruction, surface_type="any")
        if pipeline is None:
            return None

        logger.info("Pipeline fast-path: matched '%s' for '%s'", pipeline.name, instruction[:60])
        executor = PipelineExecutor()
        return await executor.execute(pipeline, self._surface, params)

    async def _capture_surface_state(self) -> dict:
        """Capture current surface state for mutation tracking."""
        if self._surface is None:
            return {}
        try:
            title = await self._surface.current_title()
            url = self._surface.current_url()
            # Light fingerprint — don't capture full screenshot for performance
            return {
                "focus": url or title,
                "title": title,
                "url": url,
            }
        except Exception:
            return {}

    def _restore_method_for_class(self, action_class: str) -> RestoreMethod:
        """Map action_class to RestoreMethod per the contract."""
        return {
            "read_only": RestoreMethod.NONE,
            "recoverable": RestoreMethod.RESTORE_STATE,
            "draftable": RestoreMethod.DELETE_CREATED,
            "sensitive": RestoreMethod.RESTORE_STATE,
            "external": RestoreMethod.COMPENSATE,
            "irreversible": RestoreMethod.NONE,
        }.get(action_class, RestoreMethod.NONE)

    def _confidence_from_action(self, result: ActionResult) -> Confidence:
        """Build Confidence from an ActionResult.

        If visual grounding data is attached to the result, uses the
        evidence-based confidence from the grounding pipeline.
        Otherwise falls back to heuristic confidence.
        """
        if result.ok:
            # Check for grounding pipeline confidence
            data = result.data or {}
            visual_conf = data.get("visual_confidence")
            if visual_conf is not None:
                return Confidence(
                    score=float(visual_conf),
                    reason="Visual grounding verified",
                    factors={"ok": True, "source": "grounding_pipeline"},
                )
            return Confidence(
                score=0.9,
                reason="Action completed successfully",
                factors={"ok": True},
            )
        if result.error:
            return Confidence(
                score=0.0,
                reason=f"Action failed: {result.error.message}",
                factors={"ok": False, "error_category": str(result.error.category)},
            )
        return Confidence(score=0.5, reason="Action returned without explicit success/failure")

    def _summarize_action(self, goal: AgentGoal, result: ActionResult, duration_ms: float) -> str:
        """Build a one-line summary."""
        params_str = ", ".join(f"{k}={v!r}" for k, v in list(goal.params.items())[:3])
        status = "succeeded" if result.ok else "failed"
        return f"{goal.capability}({params_str}) {status} in {duration_ms:.0f}ms"

    def _extract_learnings(self, loop_result: Any, context: AgentContext) -> list[Learning]:
        """Extract learnings from a loop execution."""
        learnings = []
        # If the loop detected repeated actions, record as pattern
        if loop_result.loop_detections > 0:
            learnings.append(Learning(
                type="pattern",
                domain="desktop_automation",
                key="loop_detection.triggered",
                value={"count": loop_result.loop_detections},
                confidence=0.8,
                source="user_action",
            ))
        # If replanning happened, the original plan was insufficient
        if loop_result.replan_count > 0:
            learnings.append(Learning(
                type="observation",
                domain="desktop_automation",
                key="planning.replan_needed",
                value={"replan_count": loop_result.replan_count},
                confidence=0.6,
                source="user_action",
            ))
        return learnings

    def _unknown_capability_result(self, context: AgentContext, goal: AgentGoal) -> AgentResult:
        return AgentResult(
            execution_id=context.execution_id,
            status=ResultStatus.FAILURE,
            summary=f"Unknown capability: {goal.capability}",
            data={},
            confidence=Confidence(score=0.0, reason="Unknown capability"),
            issues=[Issue(
                severity=IssueSeverity.ERROR,
                code=ErrorCode.VALIDATION_ERROR,
                message=f"Unknown capability '{goal.capability}'. "
                        f"Available: {', '.join(self.capabilities)}",
            )],
        )

    def _policy_denied_result(
        self,
        context: AgentContext,
        policy_decision: PolicyDecision,
    ) -> AgentResult:
        """Construct a failure result for a policy denial.

        Centralised so every denial path (no suggestion, kept denial, or
        re-denial after failed self-evolution) returns an identical result
        shape and never falls through to execution.
        """
        return AgentResult(
            execution_id=context.execution_id,
            status=ResultStatus.FAILURE,
            summary=f"Action blocked by policy: {policy_decision.reason}",
            data={"policy_decision_id": policy_decision.policy_decision_id},
            confidence=Confidence(score=0.0, reason="Policy denied"),
            issues=[Issue(
                severity=IssueSeverity.ERROR,
                code=ErrorCode.PERMISSION_DENIED,
                message=policy_decision.reason,
            )],
        )

    # ─── Action memory integration ───────────────

    async def _record_to_memory(
        self,
        goal: AgentGoal,
        result: ActionResult,
        context: AgentContext,
    ) -> None:
        """Record action evidence to persistent memory."""
        try:
            surface_type = "desktop" if hasattr(self._surface, "_uia_walker") else "browser"
            domain = ""
            if self._surface is not None:
                with contextlib.suppress(Exception):
                    domain = self._surface.current_url() or ""

            target = goal.params.get("target", goal.params.get("query", ""))
            evidence = ActionEvidence(
                action=goal.capability,
                target_description=target,
                surface=surface_type,
                domain=domain,
                selector=goal.params.get("selector"),
                succeeded=result.ok,
                duration_ms=result.meta.duration_ms,
                successful_tier=str(result.meta.method) if result.meta.method else None,
                error=str(result.error.message) if result.error else None,
            )
            await self._memory.record(evidence)
        except Exception:
            logger.debug("Failed to record to action memory", exc_info=True)

    async def recall_memory(
        self,
        intent: str,
        surface: str = "desktop",
        domain: str = "",
    ) -> Any | None:
        """Recall a previously-seen target from action memory.

        Public API for the agent loop to use before executing an action.
        """
        try:
            return await self._memory.recall(intent, surface, domain)
        except Exception:
            logger.debug("Failed to recall from action memory", exc_info=True)
            return None

    @property
    def memory(self) -> ActionMemory:
        """Access the action memory store."""
        return self._memory

    @property
    def rate_governor(self) -> ActionRateGovernor:
        """Access the rate governor."""
        return self._rate_governor

    @property
    def latency_budget(self) -> LatencyBudget:
        """Access the latency budget tracker."""
        return self._latency_budget

    @property
    def cost_tracker(self) -> CostTracker:
        """Access the cost tracker."""
        return self._cost_tracker

    @property
    def session_budget(self) -> SessionBudget | None:
        """Access the current session budget (if initialized)."""
        return self._session_budget

    @property
    def evidence_ledger(self) -> EvidenceLedger | None:
        """Access the evidence ledger (if initialized)."""
        return self._evidence_ledger

    @property
    def policy_evolution(self) -> PolicyEvolutionEngine:
        """Access the policy evolution engine."""
        return self._policy_evolution

    @property
    def compensation(self) -> CompensationEngine:
        """Access the compensation engine."""
        return self._compensation

    @property
    def routine_scheduler(self) -> RoutineScheduler:
        """Access the routine scheduler."""
        return self._routine_scheduler

    @property
    def skill_loader(self) -> SkillLoader:
        """Access the SKILL.md loader."""
        return self._skill_loader

    @property
    def fact_store(self) -> FactStore:
        """Access the fact store."""
        return self._fact_store

    @property
    def fact_extractor(self) -> FactExtractor:
        """Access the fact extractor."""
        return self._fact_extractor

    @property
    def resource_tracker(self) -> ResourceTracker:
        """Access the resource tracker."""
        return self._resource_tracker

    async def configure_session(
        self,
        session_id: str,
        *,
        ledger_dir: str | None = None,
        session_limits: SessionLimits | None = None,
        evolution_handler: Any | None = None,
    ) -> None:
        """Initialize session-scoped safety subsystems.

        Call once at session start to enable:
          - Evidence ledger (tamper-evident audit trail)
          - Session budget tracking (action/cost/duration limits)
          - Policy self-evolution (learn from denials)

        Args:
            session_id: Unique session identifier.
            ledger_dir: Directory for JSONL ledger files. If None, ledger is disabled.
            session_limits: Custom session limits. If None, uses defaults.
            evolution_handler: Async callable for policy evolution prompts.
        """
        self._session_budget = SessionBudget(session_id=session_id)
        if session_limits is not None:
            self._session_budget_tracker = SessionBudgetTracker(session_limits)
        if evolution_handler is not None:
            self._policy_evolution = PolicyEvolutionEngine(handler=evolution_handler)
        if ledger_dir is not None:
            from pathlib import Path
            self._evidence_ledger = EvidenceLedger(
                Path(ledger_dir) / f"{session_id}.jsonl",
            )
            await self._evidence_ledger.init()
            # Wire ledger into compensation engine
            self._compensation._ledger = self._evidence_ledger
            # Track the ledger as a resource
            self._resource_tracker.track(
                "ledger", f"{session_id}.jsonl",
                metadata={"ledger_dir": ledger_dir},
            )
            # Log session start to ledger
            await self._evidence_ledger.append(
                session_id, "session:start", {"session_id": session_id},
            )

    async def terminate_session(self, reason: str = "") -> None:
        """Terminate the current session — close ledger, cleanup resources, clear budget."""
        # Cleanup all tracked resources
        cleaned = await self._resource_tracker.cleanup_all_async()
        if cleaned > 0:
            logger.info("Cleaned up %d tracked resources on session terminate", cleaned)
        if self._evidence_ledger is not None:
            if self._session_budget is not None:
                await self._evidence_ledger.append(
                    self._session_budget.session_id, "session:terminate",
                    {"reason": reason, "budget": self._session_budget_tracker.snapshot(self._session_budget)},
                )
            await self._evidence_ledger.close()
            self._evidence_ledger = None
        self._session_budget = None
        # Clear compensation registry for all executions
        self._compensation.clear_all()

    async def health(self) -> HealthStatus:
        """Run health checks on all subsystems."""
        hc = HealthCheck(
            self,
            rate_governor=self._rate_governor,
            latency_budget=self._latency_budget,
            cost_tracker=self._cost_tracker,
        )
        return await hc.check()

    def _dry_run_result(
        self, context: AgentContext, goal: AgentGoal, cap_meta: dict
    ) -> AgentResult:
        """Return a preview without side effects."""
        params_str = ", ".join(f"{k}={v!r}" for k, v in list(goal.params.items())[:3])
        return AgentResult(
            execution_id=context.execution_id,
            status=ResultStatus.DRY_RUN,
            summary=f"Would execute: {goal.capability}({params_str})",
            data={"simulated": True, "capability": goal.capability},
            confidence=Confidence(score=1.0, reason="Dry run preview"),
            metadata={"dry_run": True, "action_class": cap_meta["action_class"]},
        )

    # ─── Universal Discovery Interface ──────────

    def describe(self) -> dict[str, Any]:
        """Return the universal discovery document.

        Any caller — AI-OS kernel, MCP host, REST client, random Python
        developer — can query this to learn:
        - Who this service is (identity, version, domains)
        - What it can do (capabilities with full input/output schemas)
        - What permissions it needs
        - What features it supports
        - How to reach it (transports)

        No documentation needed. The service describes itself.
        """
        from deskaoy.policy import permissions_for_action

        capabilities: dict[str, Any] = {}
        for name, meta in CAPABILITIES.items():
            capabilities[name] = {
                "description": meta["description"],
                "action_class": meta["action_class"],
                "impact_level": meta["impact_level"],
                "cost_estimate": meta["cost_estimate"],
                "permissions": [str(p) for p in permissions_for_action(name)],
                "input": meta.get("input_schema", {"type": "object", "properties": {}}),
                "output": meta.get("output_schema", {}),
            }

        return {
            # ── Identity ──
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "version": self.version,
            "schema_version": 1,
            "domains": self.domains,

            # ── Transports ──
            "transports": ["cli", "mcp", "rest", "stdio", "python"],

            # ── Permissions ──
            "permissions_required": [
                "screen_capture",
                "accessibility_read",
                "keyboard_input",
                "mouse_input",
                "window_focus",
            ],

            # ── Capabilities with full schemas ──
            "capabilities": capabilities,

            # ── Action class definitions ──
            "action_classes": {
                "read_only": "No side effects. Pure reads. Re-running produces same result.",
                "recoverable": "Mutates existing state, can be exactly reversed by restoring before_state.",
                "draftable": "Creates new state. Undo = delete the created thing.",
                "sensitive": "Modifies high-value state. Technically recoverable but high cost if wrong.",
                "external": "Visible to outside world. Cannot be truly undone.",
                "irreversible": "Permanent. No technical undo.",
            },

            # ── Feature support ──
            "features": {
                "dry_run": True,
                "estimate": True,
                "undo": "best_effort",
                "compensation": True,
                "trace": True,
                "receipt": True,
                "policy_simulation": True,
                "cancellation": True,
            },

            # ── Runtime status ──
            "status": {
                "bridges": {
                    "policy": self._policy_bridge.is_connected,
                    "trace": self._trace_bridge.is_connected,
                },
                "circuit_breaker": {
                    "state": self._recovery_bridge.circuit_breaker.state,
                    "failures": self._recovery_bridge.circuit_breaker.failure_count,
                },
            },

            # ── AI-OS identity (when embedded in AI-OS) ──
            "aios": {
                "capability_id": "aios.first_party.deskaoy",
                "capability_type": "agent",
                "publisher": "aios",
                "entrypoint": "deskaoy.desktop_agent:DesktopAgent",
                "min_aios_version": "0.1.0",
            },
        }

    # Backward compat: schema() delegates to describe()
    def schema(self) -> dict[str, Any]:
        """Machine-readable capability schema. Alias for describe()."""
        return self.describe()
