"""WorkflowBuilder — fluent API for composing and compiling workflow blocks.

Provides a builder pattern for constructing multi-step desktop automation
workflows from typed blocks. Compiles to DAGNode lists for the DAGExecutor.

Usage::

    workflow = (WorkflowBuilder("data-entry")
        .add(FormFillBlock(id="form", fields={"name": "Alice", "email": "a@b.com"}, submit=True, submit_selector="#submit"))
        .add(WaitBlock(id="wait", condition_str="Success message visible", timeout=10))
        .add(ValidationBlock(id="check", assertion_str="Record saved"))
        .build())
    result = await DAGExecutor().execute(workflow)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from deskaoy.orchestration.blocks import WorkflowBlock
from deskaoy.orchestration.dag import DAGNode, DAGNodeResult

logger = logging.getLogger(__name__)


@dataclass
class WorkflowResult:
    """Result of executing a complete workflow."""
    name: str
    blocks_total: int
    blocks_completed: int
    blocks_failed: int
    results: list[DAGNodeResult] = field(default_factory=list)
    duration_ms: float = 0.0
    success: bool = True

    @property
    def all_passed(self) -> bool:
        return self.blocks_failed == 0


class WorkflowBuilder:
    """Fluent builder for composing workflow blocks into executable DAGs.

    Usage::

        nodes = (WorkflowBuilder("my-workflow")
            .add(FormFillBlock(...))
            .add(WaitBlock(...))
            .to_dag_nodes())
    """

    def __init__(self, name: str = "workflow") -> None:
        self.name = name
        self._blocks: list[WorkflowBlock] = []
        self._agent: Any = None

    def add(self, block: WorkflowBlock) -> WorkflowBuilder:
        """Add a block to the workflow. Returns self for chaining."""
        errors = block.validate()
        if errors:
            raise ValueError(f"Block '{block.id}' validation failed: {'; '.join(errors)}")
        self._blocks.append(block)
        return self

    def add_unsafe(self, block: WorkflowBlock) -> WorkflowBuilder:
        """Add a block without validation. For programmatic construction."""
        self._blocks.append(block)
        return self

    def set_agent(self, agent: Any) -> WorkflowBuilder:
        """Set the agent for block compilation."""
        self._agent = agent
        return self

    @property
    def blocks(self) -> list[WorkflowBlock]:
        """Get the list of blocks."""
        return list(self._blocks)

    @property
    def block_count(self) -> int:
        """Number of blocks in the workflow."""
        return len(self._blocks)

    def validate_all(self) -> dict[str, list[str]]:
        """Validate all blocks. Returns {block_id: [errors]}."""
        results = {}
        for block in self._blocks:
            errors = block.validate()
            if errors:
                results[block.id] = errors
        return results

    def to_dag_nodes(self) -> list[DAGNode]:
        """Compile all blocks into a flat list of DAGNodes.

        Blocks are compiled in order. Each block's output nodes are
        wired as dependencies of the next block's input nodes.
        """
        all_nodes: list[DAGNode] = []
        prev_output_ids: list[int] = []

        for block in self._blocks:
            nodes = block.compile(self._agent)
            if not nodes:
                continue

            # Wire dependencies: first node of this block depends on
            # last node of previous block
            if prev_output_ids and nodes[0].depends_on == []:
                nodes[0].depends_on = list(prev_output_ids)

            all_nodes.extend(nodes)
            # Track the last node(s) of this block for chaining
            prev_output_ids = [nodes[-1].id]

        return all_nodes

    def build(self) -> list[DAGNode]:
        """Alias for to_dag_nodes()."""
        return self.to_dag_nodes()

    def describe(self) -> str:
        """Get a human-readable description of the workflow."""
        lines = [f"Workflow: {self.name}", f"Blocks: {len(self._blocks)}"]
        for i, block in enumerate(self._blocks):
            lines.append(f"  {i+1}. [{block.block_type}] {block.id}")
            errors = block.validate()
            if errors:
                lines.append(f"     ⚠ {len(errors)} validation error(s)")
        return "\n".join(lines)

    @staticmethod
    def from_blocks(name: str, blocks: list[WorkflowBlock]) -> WorkflowBuilder:
        """Create a builder pre-loaded with blocks (no validation)."""
        builder = WorkflowBuilder(name)
        for block in blocks:
            builder._blocks.append(block)
        return builder
