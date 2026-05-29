"""Tests for DAGExecutor — topological execution of dependent subtasks."""

import asyncio

import pytest

from deskaoy.orchestration.dag import (
    DAGExecutor,
    DAGNode,
    DAGNodeResult,
    _topological_sort,
)


async def _ok_action(value="ok"):
    return value


async def _fail_action():
    raise RuntimeError("boom")


async def _slow_action():
    await asyncio.sleep(5)
    return "slow"


class TestTopologicalSort:
    def test_linear_chain(self):
        nodes = [
            DAGNode(id=1, action=_ok_action, depends_on=[2]),
            DAGNode(id=2, action=_ok_action, depends_on=[3]),
            DAGNode(id=3, action=_ok_action, depends_on=[]),
        ]
        waves = _topological_sort(nodes)
        assert waves == [[3], [2], [1]]

    def test_parallel_independent(self):
        nodes = [
            DAGNode(id=1, action=_ok_action, depends_on=[]),
            DAGNode(id=2, action=_ok_action, depends_on=[]),
            DAGNode(id=3, action=_ok_action, depends_on=[]),
        ]
        waves = _topological_sort(nodes)
        assert len(waves) == 1
        assert sorted(waves[0]) == [1, 2, 3]

    def test_diamond_dependency(self):
        """A → C, B → C; A and B are independent."""
        nodes = [
            DAGNode(id=1, action=_ok_action, depends_on=[]),
            DAGNode(id=2, action=_ok_action, depends_on=[]),
            DAGNode(id=3, action=_ok_action, depends_on=[1, 2]),
        ]
        waves = _topological_sort(nodes)
        assert len(waves) == 2
        assert sorted(waves[0]) == [1, 2]
        assert waves[1] == [3]

    def test_cycle_raises(self):
        nodes = [
            DAGNode(id=1, action=_ok_action, depends_on=[2]),
            DAGNode(id=2, action=_ok_action, depends_on=[1]),
        ]
        with pytest.raises(ValueError, match="Cycle detected"):
            _topological_sort(nodes)

    def test_missing_dependency_raises(self):
        nodes = [
            DAGNode(id=1, action=_ok_action, depends_on=[99]),
        ]
        with pytest.raises(ValueError, match="nonexistent"):
            _topological_sort(nodes)

    def test_single_node(self):
        nodes = [DAGNode(id=1, action=_ok_action, depends_on=[])]
        waves = _topological_sort(nodes)
        assert waves == [[1]]

    def test_empty_list(self):
        waves = _topological_sort([])
        assert waves == []


class TestDAGExecutor:
    @pytest.mark.asyncio
    async def test_single_node_success(self):
        nodes = [DAGNode(id=1, action=lambda: _ok_action("result"), depends_on=[])]
        executor = DAGExecutor()
        results = await executor.execute(nodes)
        assert len(results) == 1
        assert results[0].ok is True
        assert results[0].result == "result"

    @pytest.mark.asyncio
    async def test_linear_chain(self):
        order = []

        async def make_action(n):
            async def action():
                order.append(n)
                return f"step_{n}"
            return action

        nodes = [
            DAGNode(id=1, action=await make_action(1), depends_on=[]),
            DAGNode(id=2, action=await make_action(2), depends_on=[1]),
            DAGNode(id=3, action=await make_action(3), depends_on=[2]),
        ]
        executor = DAGExecutor()
        results = await executor.execute(nodes)
        assert all(r.ok for r in results)
        assert order == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_parallel_independent(self):
        order = []

        async def make_action(n):
            async def action():
                order.append(n)
                await asyncio.sleep(0.01)
                return n
            return action

        nodes = [
            DAGNode(id=1, action=await make_action(1), depends_on=[]),
            DAGNode(id=2, action=await make_action(2), depends_on=[]),
        ]
        executor = DAGExecutor()
        results = await executor.execute(nodes)
        assert all(r.ok for r in results)
        assert sorted(order) == [1, 2]

    @pytest.mark.asyncio
    async def test_failure_aborts_remaining(self):
        nodes = [
            DAGNode(id=1, action=_fail_action, depends_on=[]),
            DAGNode(id=2, action=lambda: _ok_action("should not run"), depends_on=[1]),
        ]
        executor = DAGExecutor(abort_on_failure=True)
        results = await executor.execute(nodes)
        assert results[0].ok is False
        assert results[1].ok is False
        assert "upstream" in results[1].error

    @pytest.mark.asyncio
    async def test_no_abort_on_failure(self):
        nodes = [
            DAGNode(id=1, action=_fail_action, depends_on=[]),
            DAGNode(id=2, action=lambda: _ok_action("independent"), depends_on=[]),
        ]
        executor = DAGExecutor(abort_on_failure=False)
        results = await executor.execute(nodes)
        assert results[0].ok is False
        assert results[1].ok is True

    @pytest.mark.asyncio
    async def test_timeout(self):
        nodes = [
            DAGNode(id=1, action=_slow_action, depends_on=[], timeout=0.1),
        ]
        executor = DAGExecutor()
        results = await executor.execute(nodes)
        assert results[0].ok is False
        assert "Timeout" in results[0].error

    @pytest.mark.asyncio
    async def test_empty_nodes(self):
        executor = DAGExecutor()
        results = await executor.execute([])
        assert results == []

    @pytest.mark.asyncio
    async def test_diamond_dependency(self):
        order = []

        async def make_action(n):
            async def action():
                order.append(n)
                return n
            return action

        nodes = [
            DAGNode(id=1, action=await make_action(1), depends_on=[]),
            DAGNode(id=2, action=await make_action(2), depends_on=[]),
            DAGNode(id=3, action=await make_action(3), depends_on=[1, 2]),
        ]
        executor = DAGExecutor()
        results = await executor.execute(nodes)
        assert all(r.ok for r in results)
        # 1 and 2 run before 3
        assert order[-1] == 3

    @pytest.mark.asyncio
    async def test_duration_ms_recorded(self):
        nodes = [DAGNode(id=1, action=lambda: _ok_action(), depends_on=[])]
        executor = DAGExecutor()
        results = await executor.execute(nodes)
        assert results[0].duration_ms >= 0

    @pytest.mark.asyncio
    async def test_node_label_preserved(self):
        nodes = [DAGNode(id=1, action=lambda: _ok_action(), depends_on=[], label="outlook")]
        executor = DAGExecutor()
        results = await executor.execute(nodes)
        # Label is on the node, not the result — verify node has it
        assert nodes[0].label == "outlook"
