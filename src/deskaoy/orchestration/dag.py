"""DAGExecutor — topological execution of dependent subtasks.

Executes a directed acyclic graph of async callables, respecting
dependency order and parallelizing independent nodes.

Usage:
    nodes = [
        DAGNode(id=1, action=fetch_email, depends_on=[], outputs=["email.subject"]),
        DAGNode(id=2, action=create_task, depends_on=[1], outputs=["task.url"]),
    ]
    results = await DAGExecutor().execute(nodes)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DAGNode:
    """A node in the execution DAG."""

    id: int
    action: Callable[[], Awaitable[Any]]
    depends_on: list[int] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    label: str = ""
    timeout: float = 60.0


@dataclass
class DAGNodeResult:
    """Result of executing a single DAG node."""

    node_id: int
    ok: bool
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    outputs: dict[str, Any] = field(default_factory=dict)


def _topological_sort(nodes: list[DAGNode]) -> list[list[int]]:
    """Group node IDs into execution waves.

    Wave 0 has no dependencies. Wave N depends only on waves < N.
    Returns a list of waves, where each wave is a list of node IDs
    that can execute in parallel.

    Raises ValueError if a cycle is detected.
    """
    node_map = {n.id: n for n in nodes}
    all_ids = set(node_map.keys())

    # Validate all dependencies exist
    for n in nodes:
        for dep in n.depends_on:
            if dep not in all_ids:
                raise ValueError(f"Node {n.id} depends on nonexistent node {dep}")

    # Kahn's algorithm with wave tracking
    in_degree: dict[int, int] = {n.id: len(n.depends_on) for n in nodes}
    # Reverse adjacency: dep → list of nodes that depend on it
    reverse_adj: dict[int, list[int]] = defaultdict(list)
    for n in nodes:
        for dep in n.depends_on:
            reverse_adj[dep].append(n.id)

    waves: list[list[int]] = []
    ready = [nid for nid, deg in in_degree.items() if deg == 0]
    processed = 0

    while ready:
        waves.append(sorted(ready))
        next_ready: list[int] = []
        for nid in ready:
            for dependent in reverse_adj.get(nid, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    next_ready.append(dependent)
            processed += 1
        ready = next_ready

    if processed != len(nodes):
        raise ValueError("Cycle detected in DAG dependencies")

    return waves


class DAGExecutor:
    """Execute a DAG of async callables with dependency ordering.

    Nodes in the same wave run concurrently via asyncio.gather.
    Each node has an individual timeout. Execution aborts on first
    failure (configurable).
    """

    def __init__(self, *, abort_on_failure: bool = True) -> None:
        self._abort_on_failure = abort_on_failure

    async def execute(self, nodes: list[DAGNode]) -> list[DAGNodeResult]:
        """Execute all nodes respecting dependencies.

        Returns results for all nodes (failed nodes have ok=False).
        """
        if not nodes:
            return []

        waves = _topological_sort(nodes)
        node_map = {n.id: n for n in nodes}
        results: dict[int, DAGNodeResult] = {}

        for _wave_idx, wave in enumerate(waves):
            # Execute all nodes in this wave concurrently
            tasks = []
            for nid in wave:
                node = node_map[nid]
                tasks.append(self._execute_node(node))

            wave_results = await asyncio.gather(*tasks, return_exceptions=True)

            for nid, wr in zip(wave, wave_results, strict=False):
                if isinstance(wr, Exception):
                    results[nid] = DAGNodeResult(
                        node_id=nid, ok=False,
                        error=str(wr), duration_ms=0.0,
                    )
                else:
                    results[nid] = wr

            # Check for failures
            if self._abort_on_failure:
                for nid in wave:
                    if not results[nid].ok:
                        # Mark remaining nodes as failed
                        remaining = [n.id for n in nodes if n.id not in results]
                        for rid in remaining:
                            results[rid] = DAGNodeResult(
                                node_id=rid, ok=False,
                                error="Aborted: upstream node failed",
                            )
                        return list(results.values())

        return [results[n.id] for n in nodes]

    async def _execute_node(self, node: DAGNode) -> DAGNodeResult:
        """Execute a single node with timeout."""
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(node.action(), timeout=node.timeout)
            duration_ms = (time.monotonic() - start) * 1000
            return DAGNodeResult(
                node_id=node.id,
                ok=True,
                result=result,
                duration_ms=duration_ms,
            )
        except TimeoutError:
            duration_ms = (time.monotonic() - start) * 1000
            return DAGNodeResult(
                node_id=node.id,
                ok=False,
                error=f"Timeout after {node.timeout}s",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            return DAGNodeResult(
                node_id=node.id,
                ok=False,
                error=str(exc),
                duration_ms=duration_ms,
            )
