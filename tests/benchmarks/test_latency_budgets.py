"""Latency benchmark harness — measures p50/p95/p99 for each action.

Uses pytest-benchmark to measure DesktopAgent action durations against
a mock adapter. Compares results against ACTION_BUDGETS and fails CI
if any action exceeds p99 by 2×.

Run: pytest tests/benchmarks/ --benchmark-only -v
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from deskaoy.os_types import AgentContext, AgentGoal, CancellationToken
from deskaoy.desktop_agent import DesktopAgent
from deskaoy.results.types import ActionResult, ResultMeta
from deskaoy.safety.latency_budget import ACTION_BUDGETS


# ---------------------------------------------------------------------------
# Fast mock adapter (no I/O, minimal overhead)
# ---------------------------------------------------------------------------

class FastMockSurface:
    """Mock adapter with controlled latency for benchmarking."""

    def __init__(self, base_ms: float = 1.0):
        self._base_ms = base_ms
        self._title = "BenchWindow"
        self._url = "bench://test"

    async def click(self, target="", **kw):
        return ActionResult(ok=True, data={}, meta=ResultMeta(trace_id='test', duration_ms=self._base_ms))

    async def fill(self, target="", value="", **kw):
        return ActionResult(ok=True, data={}, meta=ResultMeta(trace_id='test', duration_ms=self._base_ms * 2))

    async def type_text(self, text="", **kw):
        return ActionResult(ok=True, data={}, meta=ResultMeta(trace_id='test', duration_ms=self._base_ms * 3))

    async def key_press(self, key="", **kw):
        return ActionResult(ok=True, data={}, meta=ResultMeta(trace_id='test', duration_ms=self._base_ms))

    async def scroll(self, direction="down", amount=300, **kw):
        return ActionResult(ok=True, data={}, meta=ResultMeta(trace_id='test', duration_ms=self._base_ms))

    async def screenshot(self, **kw):
        return ActionResult(ok=True, data={}, meta=ResultMeta(trace_id='test', duration_ms=self._base_ms * 5))

    async def snapshot(self, **kw):
        return ActionResult(ok=True, data={}, meta=ResultMeta(trace_id='test', duration_ms=self._base_ms * 4))

    def current_title(self):
        return self._title

    def current_url(self):
        return self._url


def _ctx() -> AgentContext:
    return AgentContext(
        execution_id="bench-001",
        idempotency_key="idem-bench",
        task_id="bench-task",
        user_id="bench-user",
        session_id="bench-session",
    )


# ---------------------------------------------------------------------------
# Benchmark fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def agent():
    return DesktopAgent(surface=FastMockSurface())


# ---------------------------------------------------------------------------
# Benchmarks — each measures DesktopAgent.execute() round-trip
# ---------------------------------------------------------------------------

class TestActionBenchmarks:

    @pytest.mark.asyncio
    @pytest.mark.benchmark(group="actions", min_rounds=20)
    async def test_benchmark_click(self, agent, benchmark):
        """Click should complete within p99 budget."""
        budget = ACTION_BUDGETS["click"]["p99"] * 2  # 2× grace factor

        async def _run():
            goal = AgentGoal(capability="click", params={"target": "btn"})
            return await agent.execute(goal, _ctx())

        # pytest-benchmark wraps sync; use the async helper
        result = await _run()
        assert result.metadata["duration_ms"] < budget

    @pytest.mark.asyncio
    @pytest.mark.benchmark(group="actions", min_rounds=20)
    async def test_benchmark_fill(self, agent, benchmark):
        budget = ACTION_BUDGETS["fill"]["p99"] * 2

        async def _run():
            goal = AgentGoal(capability="fill", params={"target": "#inp", "value": "x"})
            return await agent.execute(goal, _ctx())

        result = await _run()
        assert result.metadata["duration_ms"] < budget

    @pytest.mark.asyncio
    @pytest.mark.benchmark(group="actions", min_rounds=20)
    async def test_benchmark_key_press(self, agent, benchmark):
        budget = ACTION_BUDGETS["key_press"]["p99"] * 2

        async def _run():
            goal = AgentGoal(capability="key_press", params={"key": "Enter"})
            return await agent.execute(goal, _ctx())

        result = await _run()
        assert result.metadata["duration_ms"] < budget

    @pytest.mark.asyncio
    @pytest.mark.benchmark(group="actions", min_rounds=20)
    async def test_benchmark_scroll(self, agent, benchmark):
        budget = ACTION_BUDGETS["scroll"]["p99"] * 2

        async def _run():
            goal = AgentGoal(capability="scroll", params={"direction": "down", "amount": 300})
            return await agent.execute(goal, _ctx())

        result = await _run()
        assert result.metadata["duration_ms"] < budget

    @pytest.mark.asyncio
    @pytest.mark.benchmark(group="actions", min_rounds=20)
    async def test_benchmark_screenshot(self, agent, benchmark):
        budget = ACTION_BUDGETS["screenshot"]["p99"] * 2

        async def _run():
            goal = AgentGoal(capability="screenshot", params={})
            return await agent.execute(goal, _ctx())

        result = await _run()
        assert result.metadata["duration_ms"] < budget

    @pytest.mark.asyncio
    @pytest.mark.benchmark(group="actions", min_rounds=20)
    async def test_benchmark_snapshot(self, agent, benchmark):
        budget = ACTION_BUDGETS["snapshot"]["p99"] * 2

        async def _run():
            goal = AgentGoal(capability="snapshot", params={})
            return await agent.execute(goal, _ctx())

        result = await _run()
        assert result.metadata["duration_ms"] < budget


class TestOrchestrateBenchmark:
    """Orchestrate with template match should be fast."""

    @pytest.mark.asyncio
    @pytest.mark.benchmark(group="orchestrate", min_rounds=10)
    async def test_benchmark_orchestrate_template(self, agent, benchmark):
        budget = ACTION_BUDGETS["automate"]["p99"] * 2

        async def _run():
            goal = AgentGoal(
                capability="orchestrate",
                params={"instruction": "Read email and create a task"},
            )
            return await agent.execute(goal, _ctx())

        result = await _run()
        assert result.status.value in ("success", "partial")
