"""SubagentDelegator — parallel child agents with isolated browser contexts."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from deskaoy.agent.loop import AgentLoop
from deskaoy.agent.registry import ToolRegistry
from deskaoy.agent.types import ChildTask, DelegationResult, DelegationStatus

logger = logging.getLogger(__name__)


class SubagentDelegator:

    def __init__(
        self,
        session: Any,
        registry: ToolRegistry,
        llm_client: Any,
        *,
        controller_factory: Any | None = None,
        max_concurrency: int = 4,
        max_steps_per_child: int = 50,
        # C5: subsystem references for child agents
        recovery_coordinator: Any | None = None,
        budget_client: Any | None = None,
        flow_logger: Any | None = None,
        security_manager: Any | None = None,
        stealth_manager: Any | None = None,
    ) -> None:
        self._session = browser_session
        self._registry = registry
        self._llm = llm_client
        self._max_concurrency = max_concurrency
        self._max_steps = max_steps_per_child
        # C5: store subsystems
        self._recovery_coordinator = recovery_coordinator
        self._budget_client = budget_client
        self._flow_logger = flow_logger
        self._security_manager = security_manager
        self._stealth_manager = stealth_manager

    async def delegate(
        self,
        tasks: list[str],
        *,
        max_concurrency: int | None = None,
        abort_signal: asyncio.Event | None = None,
    ) -> DelegationResult:
        start = time.monotonic()
        concurrency = max_concurrency or self._max_concurrency
        semaphore = asyncio.Semaphore(concurrency)

        children = [ChildTask(instruction=instr) for instr in tasks]

        async def _run_with_semaphore(task: ChildTask) -> ChildTask:
            async with semaphore:
                if abort_signal and abort_signal.is_set():
                    task.status = DelegationStatus.CANCELLED
                    return task
                return await self._run_child(task)

        results = await asyncio.gather(
            *[_run_with_semaphore(c) for c in children],
            return_exceptions=True,
        )

        final_tasks: list[ChildTask] = []
        for r in results:
            if isinstance(r, Exception):
                failed = ChildTask(instruction="error", status=DelegationStatus.FAILED, result=str(r))
                final_tasks.append(failed)
            else:
                final_tasks.append(r)

        duration = (time.monotonic() - start) * 1000
        completed = sum(1 for t in final_tasks if t.status == DelegationStatus.COMPLETED)
        failed = sum(1 for t in final_tasks if t.status == DelegationStatus.FAILED)
        cancelled = sum(1 for t in final_tasks if t.status == DelegationStatus.CANCELLED)

        return DelegationResult(
            tasks=final_tasks,
            total_duration_ms=duration,
            completed_count=completed,
            failed_count=failed,
            cancelled_count=cancelled,
        )

    async def _run_child(self, task: ChildTask) -> ChildTask:
        task.status = DelegationStatus.RUNNING
        task.started_at = time.monotonic()

        page = None
        try:
            page = await self._session.new_page()

            if self._controller_factory:
                controller = self._controller_factory(page)
            else:
                raise RuntimeError("No controller_factory provided to SubagentDelegator")

            child_loop = AgentLoop(
                controller=controller,
                registry=self._registry,
                llm_client=self._llm,
                max_steps=self._max_steps,
                recovery_coordinator=self._recovery_coordinator,   # C5
                budget_client=self._budget_client,                 # C5
                flow_logger=self._flow_logger,                     # C5
                security_manager=self._security_manager,           # C5
                stealth_manager=self._stealth_manager,             # C5
            )
            loop_result = await child_loop.run(task.instruction)

            task.result = loop_result
            task.status = DelegationStatus.COMPLETED

        except Exception as exc:
            logger.warning("Child task %s failed: %s", task.task_id[:8], exc)
            task.result = str(exc)
            task.status = DelegationStatus.FAILED
        finally:
            if page:
                with contextlib.suppress(Exception):
                    await page.close()

        task.completed_at = time.monotonic()
        return task
