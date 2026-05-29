"""AgentLoop — step-based LLM interaction cycle with loop detection and planning."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from deskaoy.agent.context import build_step_context
from deskaoy.agent.loop_detector import ActionLoopDetector
from deskaoy.agent.registry import ToolRegistry
from deskaoy.agent.types import (
    LoopNudge,
    LoopResult,
    PlanItem,
    PlanStatus,
    StepEvent,
    StepResult,
)
from deskaoy.hooks import HookContext, HookName
from deskaoy.hooks import hooks as global_hooks
from deskaoy.memory.store import ActionMemory
from deskaoy.memory.types import ActionEvidence, TierRecord
from deskaoy.results import ActionError, ActionResult, ErrorCategory, action_result

logger = logging.getLogger(__name__)


class AgentLoop:

    def __init__(
        self,
        controller: Any,
        registry: ToolRegistry,
        llm_client: Any,
        *,
        max_steps: int = 50,
        loop_detector: ActionLoopDetector | None = None,
        abort_signal: asyncio.Event | None = None,
        event_callback: Callable[[StepEvent, dict], Awaitable[None]] | None = None,
        stagnation_threshold: int = 3,
        recovery_coordinator: Any | None = None,
        budget_client: Any | None = None,
        flow_logger: Any | None = None,
        security_manager: Any | None = None,
        stealth_manager: Any | None = None,
        step_timeout: float = 30.0,  # M15: per-step timeout
        memory: ActionMemory | None = None,
        two_step: bool = False,  # BATCH-06: two-step action verification
    ) -> None:
        self._controller = controller
        self._registry = registry
        self._llm = llm_client
        self._max_steps = max_steps
        self._loop_detector = loop_detector or ActionLoopDetector()
        self._abort_signal = abort_signal
        self._event_callback = event_callback
        self._stagnation_threshold = stagnation_threshold
        self._recovery_coordinator = recovery_coordinator
        self._budget_client = budget_client
        self._flow_logger = flow_logger
        self._security_manager = security_manager
        self._stealth_manager = stealth_manager
        self._step_timeout = step_timeout
        self._memory = memory
        self._two_step = two_step
        self._verifier = None
        self._last_memory_anchor: str | None = None

    async def run(
        self,
        instruction: str,
        *,
        abort_signal: asyncio.Event | None = None,
        initial_plan: list[PlanItem] | None = None,
    ) -> LoopResult:
        signal = abort_signal or self._abort_signal
        start = time.monotonic()
        steps: list[StepResult] = []
        loop_detections = 0
        replan_count = 0
        plan = list(initial_plan) if initial_plan else []
        stalled_count = 0
        prev_fingerprint = ""

        if self._flow_logger:
            async with self._flow_logger.trace(instruction[:64]):
                return await self._run_loop(
                    instruction, signal, start, steps, plan,
                    loop_detections, replan_count, stalled_count, prev_fingerprint,
                )
        return await self._run_loop(
            instruction, signal, start, steps, plan,
            loop_detections, replan_count, stalled_count, prev_fingerprint,
        )

    async def _run_loop(
        self, instruction, signal, start, steps, plan,
        loop_detections, replan_count, stalled_count, prev_fingerprint,
    ) -> LoopResult:
        if not plan:
            plan = await self._request_initial_plan(instruction)

        nudge: LoopNudge | None = None  # C1: track nudge across steps

        for step_num in range(1, self._max_steps + 1):
            if signal and signal.is_set():
                await self._emit(StepEvent.ABORT, {"step_number": step_num})
                return self._build_result(instruction, steps, plan, "abort", start, loop_detections, replan_count)

            await self._emit(StepEvent.STEP_START, {"step_number": step_num})

            step_start = time.monotonic()
            try:
                tool_api = self._registry.build_tool_api_description()
                prompt = self._build_prompt(instruction, plan, steps, tool_api, nudge=nudge)
                llm_response = await self._llm.propose_action(prompt)

                if llm_response.get("done"):
                    duration = (time.monotonic() - step_start) * 1000
                    steps.append(StepResult(step_num, "done", {}, None, duration))
                    await self._emit(StepEvent.STEP_COMPLETE, {"step_number": step_num, "action": "done"})
                    return self._build_result(instruction, steps, plan, "success", start, loop_detections, replan_count)

                action_name = llm_response.get("action", "")
                action_params = llm_response.get("params", {})
                memory_hit = False

                # ─── Memory recall: inject cached anchors ───
                if self._memory and action_name in ("click", "fill", "select", "hover", "drag", "scroll", "type"):
                    recalled_params = await self._try_memory_recall(action_name, action_params)
                    if recalled_params is not None:
                        action_params = recalled_params
                        memory_hit = True

                action_record = {"action": action_name, **action_params}
                nudge = self._loop_detector.record_and_check(action_record)  # C2: always run loop detection
                if nudge:
                    loop_detections += 1
                    await self._emit(StepEvent.LOOP_DETECTED, {
                        "step_number": step_num, "level": nudge.level, "count": nudge.repetition_count,
                    })
                    if nudge.level >= 3:
                        return self._build_result(instruction, steps, plan, "loop_detected", start, loop_detections, replan_count)

                if self._recovery_coordinator:
                    try:
                        result = await asyncio.wait_for(
                            self._recovery_coordinator.execute_with_recovery(
                                action_fn=lambda: self._dispatch_action(action_name, action_params),
                                action_context={
                                    "action_type": action_name,
                                    "params": action_params,
                                    "target": action_params.get("target", ""),
                                    "value": action_params.get("value", ""),
                                    "step": step_num,
                                },
                            ),
                            timeout=self._step_timeout,
                        )
                    except TimeoutError:
                        duration = (time.monotonic() - step_start) * 1000
                        steps.append(StepResult(step_num, "timeout", {}, None, duration, error="Step timed out"))
                        await global_hooks.emit(HookName.ON_STEP_ERROR, HookContext(
                            command=action_name, args=action_params, error=TimeoutError(),
                            started_at=step_start, finished_at=time.monotonic(),
                            extra={"step_number": step_num},
                        ))
                        await self._emit(StepEvent.STEP_ERROR, {"step_number": step_num, "error": "timeout"})
                        continue
                else:
                    try:
                        result = await asyncio.wait_for(
                            self._dispatch_action(action_name, action_params),
                            timeout=self._step_timeout,
                        )
                    except TimeoutError:
                        duration = (time.monotonic() - step_start) * 1000
                        steps.append(StepResult(step_num, "timeout", {}, None, duration, error="Step timed out"))
                        await self._emit(StepEvent.STEP_ERROR, {"step_number": step_num, "error": "timeout"})
                        continue
                duration = (time.monotonic() - step_start) * 1000

                new_fingerprint = await self._compute_page_fingerprint()
                page_changed = self._detect_page_change(prev_fingerprint, new_fingerprint)
                prev_fingerprint = new_fingerprint

                if page_changed:
                    stalled_count = 0
                    self._advance_plan(step_num, plan, action_name, result)
                else:
                    stalled_count += 1

                step_result = StepResult(
                    step_number=step_num,
                    action_name=action_name,
                    action_params=action_params,
                    action_result=result,
                    duration_ms=duration,
                    page_changed=page_changed,
                )

                # ─── Two-step verification (BATCH-06) ───
                if self._two_step and result is not None:
                    step_result = await self._verify_step(
                        step_result, action_name, action_params
                    )

                steps.append(step_result)

                # ─── Memory record: store evidence ───
                if self._memory and result is not None:
                    await self._record_step_evidence(action_name, action_params, result, memory_hit)
                await global_hooks.emit(HookName.ON_STEP_COMPLETE, HookContext(
                    command=action_name, args=action_params,
                    started_at=step_start, finished_at=time.monotonic(),
                    extra={"step_number": step_num, "ok": result.ok if result else False},
                ))
                await self._emit(StepEvent.STEP_COMPLETE, {
                    "step_number": step_num, "action": action_name, "duration_ms": duration,
                })

                if stalled_count >= self._stagnation_threshold:
                    plan = await self._auto_replan(instruction, plan, steps)
                    replan_count += 1
                    stalled_count = 0
                    await self._emit(StepEvent.PLAN_UPDATED, {"step_number": step_num, "replan_count": replan_count})

            except Exception as exc:
                duration = (time.monotonic() - step_start) * 1000
                steps.append(StepResult(step_num, "error", {}, None, duration, error=str(exc)))
                await global_hooks.emit(HookName.ON_STEP_ERROR, HookContext(
                    command="", args={}, error=exc,
                    started_at=step_start, finished_at=time.monotonic(),
                    extra={"step_number": step_num},
                ))
                await self._emit(StepEvent.STEP_ERROR, {"step_number": step_num, "error": str(exc)})

        await self._emit(StepEvent.MAX_STEPS_REACHED, {"total_steps": self._max_steps})
        return self._build_result(instruction, steps, plan, "max_steps", start, loop_detections, replan_count)

    # -- Plan management --

    async def _request_initial_plan(self, instruction: str) -> list[PlanItem]:
        try:
            raw_plan = await self._llm.create_plan(instruction, self._registry.build_tool_api_description())
            return [
                PlanItem(index=i, description=item.get("description", f"Step {i+1}"))
                for i, item in enumerate(raw_plan)
            ]
        except Exception:
            return [PlanItem(index=0, description=instruction)]

    async def _auto_replan(self, instruction: str, plan: list[PlanItem], steps: list[StepResult]) -> list[PlanItem]:
        recent = steps[-5:] if len(steps) >= 5 else steps
        try:
            raw_plan = await self._llm.replan(
                instruction=instruction,
                current_plan=[{"index": p.index, "description": p.description, "status": p.status.value} for p in plan],
                recent_actions=[{"action": s.action_name, "params": s.action_params} for s in recent],
            )
            return [
                PlanItem(index=i, description=item.get("description", f"Step {i+1}"))
                for i, item in enumerate(raw_plan)
            ]
        except Exception:
            return plan

    def _advance_plan(self, step_num: int, plan: list[PlanItem], action_name: str, result: ActionResult) -> None:
        for item in plan:
            if item.status == PlanStatus.PENDING:
                item.status = PlanStatus.DONE if result.ok else PlanStatus.FAILED
                item.action_taken = action_name
                item.result_summary = "ok" if result.ok else "failed"
                item.completed_at = time.monotonic()
                break

    # -- Action dispatch --

    async def _dispatch_action(self, action_name: str, params: dict) -> ActionResult:
        tool = self._registry.get(action_name)
        if tool is None:
            return action_result(
                ok=False,
                error=ActionError(
                    ErrorCategory.VALIDATION, f"Unknown tool: {action_name}"
                ),
            )
        if self._security_manager:
            from deskaoy.security.types import SecurityLevel
            sec_level = SecurityLevel(tool.security_level) if tool.security_level in ("safe", "sensitive", "dangerous") else SecurityLevel.SENSITIVE
            url = self._controller._page.url if self._controller and hasattr(self._controller, '_page') and self._controller._page else ""
            sec_result = await self._security_manager.check_action(
                action_name, params, url, sec_level,
            )
            if not sec_result.passed:
                return action_result(
                    ok=False,
                    error=ActionError(
                        ErrorCategory.SECURITY,
                        f"Security check failed: {sec_result.blocked_by}",
                    ),
                )
        if self._stealth_manager:
            url = self._controller._page.url if self._controller and hasattr(self._controller, '_page') and self._controller._page else ""
            decision = self._stealth_manager.evaluate_action(action_name, url)
            if decision.verdict.value == "deny":
                return action_result(
                    ok=False,
                    error=ActionError(
                        ErrorCategory.SECURITY,
                        f"Stealth policy denied: {action_name}",
                    ),
                )
            if decision.verdict.value == "confirm":
                cb = getattr(self._stealth_manager.config, "confirm_callback", None)
                if cb and not cb(action_name, url):
                    return action_result(
                        ok=False,
                        error=ActionError(
                            ErrorCategory.SECURITY,
                            f"Stealth policy requires confirmation: {action_name}",
                        ),
                    )
        try:
            result = tool.handler(**params)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as exc:
            return action_result(
                ok=False,
                error=ActionError(
                    ErrorCategory.UNKNOWN, str(exc)
                ),
            )

    # -- Page fingerprinting --

    async def _compute_page_fingerprint(self) -> str:
        try:
            url = self._controller._page.url
            title = await self._controller._page.title()

            # H7: enrich fingerprint with DOM node count, interactive elements,
            # and scroll position so scrolling and dynamic content changes are detected
            dom_state = ""
            try:
                cdp = getattr(self._controller, '_cdp', None)
                if cdp and hasattr(cdp, 'send'):
                    result = await cdp.send("Runtime.evaluate", {
                        "expression": (
                            '(function(){'
                            'var n=document.querySelectorAll("*").length;'
                            'var i=document.querySelectorAll("a,button,input,select,textarea,[onclick],[role]").length;'
                            'var s=Math.round(window.scrollY||0);'
                            'return JSON.stringify({n:n,i:i,s:s});'
                            '})()'
                        ),
                        "returnByValue": True,
                    })
                    if hasattr(result, 'ok') and result.ok and hasattr(result, 'data') and result.data:
                        dom_state = result.data.get("result", {}).get("value", "")
                elif cdp and hasattr(cdp, 'evaluate'):
                    result = await cdp.evaluate(
                        '(function(){'
                        'var n=document.querySelectorAll("*").length;'
                        'var i=document.querySelectorAll("a,button,input,select,textarea,[onclick],[role]").length;'
                        'var s=Math.round(window.scrollY||0);'
                        'return JSON.stringify({n:n,i:i,s:s});'
                        '})()'
                    )
                    if hasattr(result, 'ok') and result.ok and hasattr(result, 'data') and result.data:
                        dom_state = result.data.get("result", {}).get("value", "")
            except Exception:
                pass

            raw = f"{url}|{title}|{dom_state}"
            return hashlib.sha256(raw.encode()).hexdigest()[:16]
        except Exception:
            return ""

    def _detect_page_change(self, before: str, after: str) -> bool:
        return before != after and before != "" and after != ""

    # -- Action memory helpers --

    async def _try_memory_recall(self, action_name: str, params: dict) -> dict | None:
        """Try to recall a cached anchor from action memory.

        Returns modified params with the cached target injected, or None on miss.
        """
        target = params.get("target", params.get("selector", ""))
        if not target:
            return None

        surface = self._detect_surface()
        domain = self._detect_domain()

        try:
            recalled = await self._memory.recall(target, surface, domain)
        except Exception:
            logger.debug("Memory recall failed", exc_info=True)
            return None

        if recalled is None:
            return None

        # Get the best anchor value to use
        anchors = []
        if recalled.selector:
            anchors.append(("selector", recalled.selector, 0.9))
        if recalled.ax_path:
            anchors.append(("ax_path", recalled.ax_path, 0.85))
        if recalled.uia_automation_id:
            anchors.append(("uia_id", recalled.uia_automation_id, 0.8))
        if recalled.uia_name:
            anchors.append(("uia_name", recalled.uia_name, 0.75))
        if recalled.ocr_text:
            anchors.append(("ocr", recalled.ocr_text, 0.6))

        if not anchors:
            return None

        # Pick the highest-confidence anchor
        best_kind, best_value, _ = max(anchors, key=lambda x: x[2])

        modified = dict(params)
        modified["target"] = best_value
        # Store anchor kind in a separate tracking dict, not in params
        # (params get passed to tool.handler(**params) which rejects unknown kwargs)
        self._last_memory_anchor = best_kind
        logger.debug(
            "Memory hit for '%s': using %s anchor '%s'",
            target, best_kind, best_value,
        )
        return modified

    async def _record_step_evidence(
        self,
        action_name: str,
        params: dict,
        result: ActionResult,
        memory_hit: bool,
    ) -> None:
        """Record action evidence to memory after execution."""
        target = params.get("target", params.get("selector", ""))
        if not target:
            return

        surface = self._detect_surface()
        domain = self._detect_domain()

        anchor_used = self._last_memory_anchor or "selector"
        self._last_memory_anchor = None
        tier_attempts = []
        if result.ok:
            tier_attempts.append(TierRecord(
                tier="memory_recall" if memory_hit else anchor_used,
                outcome="success" if not memory_hit else "memory_hit",
                duration_ms=result.meta.duration_ms if result.meta else 0,
                anchor_used=anchor_used,
            ))

        evidence = ActionEvidence(
            action=action_name,
            target_description=target,
            surface=surface,
            domain=domain,
            selector=params.get("selector"),
            succeeded=result.ok,
            duration_ms=result.meta.duration_ms if result.meta else 0,
            successful_tier=anchor_used if result.ok else None,
            error=str(result.error.message) if result.error else None,
            tier_attempts=tier_attempts,
        )
        try:
            await self._memory.record(evidence)
        except Exception:
            logger.debug("Memory record failed", exc_info=True)

    def _detect_surface(self) -> str:
        """Detect the surface type from the controller."""
        ctrl = self._controller
        if ctrl is None:
            return "unknown"
        type(ctrl).__module__ or ""
        # Detect browser surface by checking for browser-specific attributes
        if hasattr(ctrl, "_cdp") or hasattr(ctrl, "_page"):
            return "browser"
        if hasattr(ctrl, "_uia_walker"):
            return "desktop"
        return "unknown"

    def _detect_domain(self) -> str:
        """Detect the current domain from the controller."""
        ctrl = self._controller
        if ctrl is None:
            return ""
        try:
            if hasattr(ctrl, "_page") and ctrl._page:
                from urllib.parse import urlparse
                return urlparse(getattr(ctrl._page, "url", "")).hostname or ""
        except Exception:
            pass
        try:
            if hasattr(ctrl, "current_url"):
                from urllib.parse import urlparse
                return urlparse(ctrl.current_url()).hostname or ""
        except Exception:
            pass
        return ""

    # -- Utilities --

    # -- Two-step verification (BATCH-06) --

    async def _verify_step(
        self, step_result: StepResult, action_name: str, action_params: dict
    ) -> StepResult:
        """Capture post-action snapshot and verify action outcome."""
        try:
            # Lazy-init verifier
            if self._verifier is None:
                from deskaoy.agent.two_step import TwoStepVerifier
                self._verifier = TwoStepVerifier()

            # Capture post-action snapshot
            post_snapshot = await self._capture_snapshot()

            # We need a pre-snapshot — capture one before next action
            # For now, use a synthetic approach: compare current to a fresh snapshot
            if not hasattr(self, '_pre_snapshot') or self._pre_snapshot is None:
                self._pre_snapshot = post_snapshot
                return step_result

            # Verify
            target = action_params.get("target", action_params.get("selector", ""))
            verification = self._verifier.verify(
                self._pre_snapshot, post_snapshot, action_name, target
            )

            step_result.verification = verification
            step_result.diff_summary = (
                f"{action_name}: {'applied' if verification.action_applied else 'inconclusive'} "
                f"(confidence={verification.confidence:.2f}) — {verification.evidence}"
            )

            # Update pre-snapshot for next step
            self._pre_snapshot = post_snapshot

        except Exception as exc:
            logger.debug("Two-step verification failed: %s", exc, exc_info=True)

        return step_result

    async def _capture_snapshot(self) -> Any:
        """Capture current accessibility snapshot from the controller."""
        try:
            if self._controller and hasattr(self._controller, 'snapshot'):
                result = self._controller.snapshot()
                if asyncio.iscoroutine(result):
                    result = await result
                if isinstance(result, dict):
                    from deskaoy.cascade.types import AXSnapshot
                    return AXSnapshot(
                        url=getattr(self._controller, 'current_url', lambda: '')() or '',
                        title=await self._controller.current_title() if hasattr(self._controller, 'current_title') else '',
                        nodes=result,
                    )
                return result
        except Exception:
            pass
        from deskaoy.cascade.types import AXSnapshot
        return AXSnapshot(url="", title="")

    # -- Prompt building --

    def _build_prompt(
        self,
        instruction: str,
        plan: list[PlanItem],
        steps: list[StepResult],
        tool_api: str,
        nudge: LoopNudge | None = None,
    ) -> str:
        plan_str = "\n".join(f"  {p.index}. [{p.status.value}] {p.description}" for p in plan)
        recent = steps[-5:] if len(steps) >= 5 else steps
        history_str = "\n".join(f"  Step {s.step_number}: {s.action_name} -> {'ok' if not s.error else s.error}" for s in recent)

        # G11: inject error hint from last failed step
        error_hint_str = ""
        last_step = recent[-1] if recent else None
        if last_step and last_step.action_result and last_step.action_result.error:
            err = last_step.action_result.error
            if getattr(err, 'hint', ''):
                error_hint_str = f"\n\n💡 Last error hint: {err.hint}"

        # C1: inject loop nudge as a prominent system-level warning
        nudge_str = ""
        if nudge:
            nudge_str = (
                f"\n\n⚠️ LOOP DETECTED (level {nudge.level}, {nudge.repetition_count} repetitions)\n"
                f"Repeated action: {nudge.repeated_action}\n"
                f"Advice: {nudge.message}\n"
                f"You MUST try a completely different approach.\n"
            )

        # LangExtract pattern C: step context window
        ctx = build_step_context(steps)
        context_str = f"\n\nContext:\n{ctx.to_prompt_text()}" if ctx.has_context else ""

        # BATCH-06: inject diff context from two-step verification
        diff_str = ""
        if self._two_step:
            verified_steps = [s for s in recent if s.diff_summary]
            if verified_steps:
                diff_str = "\n\nAction Verification:\n" + "\n".join(
                    f"  Step {s.step_number}: {s.diff_summary}" for s in verified_steps
                )

        return f"Instruction: {instruction}{error_hint_str}{nudge_str}{context_str}{diff_str}\n\nPlan:\n{plan_str}\n\nRecent steps:\n{history_str}\n\n{tool_api}"

    async def _emit(self, event: StepEvent, data: dict) -> None:
        if self._event_callback:
            with contextlib.suppress(Exception):
                await self._event_callback(event, data)

    def _build_result(self, instruction, steps, plan, reason, start, detections, replans) -> LoopResult:
        return LoopResult(
            instruction=instruction,
            steps=steps,
            plan=plan,
            completion_reason=reason,
            total_duration_ms=(time.monotonic() - start) * 1000,
            total_steps=len(steps),
            loop_detections=detections,
            replan_count=replans,
        )
