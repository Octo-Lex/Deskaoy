"""Pipeline types — declarative action sequence definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineArg:
    """A declared argument that a pipeline accepts."""
    name: str
    type: type = str
    required: bool = True
    default: Any = None


@dataclass
class PipelineStep:
    """A single step in a pipeline."""
    action: str           # "click", "type_text", "key_press", "snapshot", "wait"
    params: dict[str, Any] = field(default_factory=dict)
    condition: str | None = None   # "result.ok" or "snapshot.contains('Error')"
    retry: int = 0        # number of retries on failure


@dataclass
class PipelineDefinition:
    """A complete deterministic action pipeline."""
    name: str
    description: str
    surface_type: str = "any"  # "windows", "macos", "browser", "any"
    args: list[PipelineArg] = field(default_factory=list)
    steps: list[PipelineStep] = field(default_factory=list)

    def matches_instruction(self, instruction: str) -> bool:
        """Check if this pipeline matches an instruction string.

        Simple keyword matching: all words in the pipeline name must appear
        in the instruction (case-insensitive).
        """
        inst_lower = instruction.lower()
        name_words = self.name.replace("_", " ").split()
        return all(w in inst_lower for w in name_words)
