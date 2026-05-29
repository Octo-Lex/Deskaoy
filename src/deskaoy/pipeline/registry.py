"""Pipeline registry — discover and match deterministic pipelines."""

from __future__ import annotations

import logging

from deskaoy.pipeline.types import PipelineDefinition

logger = logging.getLogger(__name__)


class PipelineRegistry:
    """Registry of known deterministic pipelines.

    Usage::

        registry = PipelineRegistry()
        registry.register(notepad_type_pipeline)

        match = registry.match("type hello world in notepad")
        if match:
            executor.execute(match, surface, {"text": "hello world"})
    """

    def __init__(self) -> None:
        self._pipelines: dict[str, PipelineDefinition] = {}

    def register(self, pipeline: PipelineDefinition) -> None:
        self._pipelines[pipeline.name] = pipeline

    def get(self, name: str) -> PipelineDefinition | None:
        return self._pipelines.get(name)

    def match(self, instruction: str, surface_type: str = "any") -> PipelineDefinition | None:
        """Find a pipeline that matches the instruction.

        Checks each pipeline's ``matches_instruction()`` method.
        If multiple match, returns the one with the most specific name
        (longest name wins).
        """
        candidates = []
        for pipeline in self._pipelines.values():
            # Surface type filter: 'any' accepts everything
            if surface_type != "any" and pipeline.surface_type != "any" and pipeline.surface_type != surface_type:
                continue
            if pipeline.matches_instruction(instruction):
                candidates.append(pipeline)

        if not candidates:
            return None

        # Return most specific (longest name = most keywords matched)
        candidates.sort(key=lambda p: len(p.name), reverse=True)
        return candidates[0]

    @property
    def all_pipelines(self) -> list[PipelineDefinition]:
        return list(self._pipelines.values())

    @property
    def count(self) -> int:
        return len(self._pipelines)
