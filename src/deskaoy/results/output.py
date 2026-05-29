"""OutputDefender — 3-level defense against context window overflow."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

from deskaoy.results.typed import SpilledResult
from deskaoy.results.types import ActionResult


@dataclass(frozen=True)
class OutputBudgetConfig:
    """Immutable budget configuration for output defense."""
    default_max_chars: int = 50_000
    spill_threshold: int = 50_000
    turn_budget: int = 200_000
    preview_length: int = 500
    per_tool_overrides: dict[str, int] = field(default_factory=dict)

    def resolve_threshold(self, tool_name: str) -> int:
        return self.per_tool_overrides.get(tool_name, self.default_max_chars)


class OutputDefender:
    """Three-level defense against context window overflow.

    Level 1: Per-tool character cap.
    Level 2: Per-result persistence — large results spill to disk.
    Level 3: Per-turn aggregate budget.

    Ported from Hermes tools/tool_result_storage.py.
    """

    def __init__(
        self,
        config: OutputBudgetConfig | None = None,
        spill_dir: Path | None = None,
        spill_threshold: int | None = None,
        turn_budget: int | None = None,
    ) -> None:
        if config is not None:
            self._config = config
        else:
            overrides: dict[str, int] = {}
            if spill_threshold is not None:
                overrides["spill_threshold"] = spill_threshold
            if turn_budget is not None:
                overrides["turn_budget"] = turn_budget
            self._config = OutputBudgetConfig(**overrides)  # type: ignore[arg-type]
        self._spill_dir = spill_dir or Path.home() / ".deskaoy" / "spill"
        self._turn_used: int = 0
        self._results: list[tuple[str, int, ActionResult]] = []  # C3: store result refs for Level 3 spill
        self._lock = threading.Lock()

    def new_turn(self) -> None:
        """Reset per-turn budget at the start of a new agent turn."""
        with self._lock:
            self._turn_used = 0
            self._results.clear()

    def defend(self, result: ActionResult, max_chars: int) -> ActionResult:
        """Apply all three defense levels to a result."""
        with self._lock:
            serialized = result.to_json()
            char_count = len(serialized)

            # Level 1: Per-tool cap
            if char_count > max_chars:
                result = self._truncate_data(result, max_chars)
                serialized = result.to_json()
                char_count = len(serialized)

            # Level 2: Per-result spill
            if char_count > self._config.spill_threshold:
                result = self._spill_to_disk(result, char_count)
                char_count = self._config.preview_length

            # Level 3: Per-turn budget
            self._turn_used += char_count
            self._results.append((result.meta.trace_id, char_count, result))  # C3: store result ref

            if self._turn_used > self._config.turn_budget:
                self._spill_largest_results()

        return result

    @property
    def turn_used(self) -> int:
        with self._lock:
            return self._turn_used

    @property
    def turn_budget(self) -> int:
        return self._config.turn_budget

    @property
    def turn_remaining(self) -> int:
        with self._lock:
            return max(0, self._config.turn_budget - self._turn_used)

    def _truncate_data(self, result: ActionResult, max_chars: int) -> ActionResult:
        """Level 1: Truncate the data payload to fit within max_chars."""
        if isinstance(result.data, dict):
            serialized = json.dumps(result.data, default=str)
            if len(serialized) > max_chars:
                # Truncate string values proportionally
                truncated = {}
                n_keys = max(len(result.data), 1)
                per_key = max_chars // n_keys
                for k, v in result.data.items():
                    if isinstance(v, str) and len(v) > per_key:
                        truncated[k] = v[:per_key] + "\n... [truncated]"
                    else:
                        truncated[k] = v
                truncated["truncated"] = True
                result.data = truncated
        elif isinstance(result.data, str):
            if len(result.data) > max_chars:
                result.data = result.data[:max_chars] + "\n... [truncated]"
        elif isinstance(result.data, list):
            serialized = json.dumps(result.data, default=str)
            if len(serialized) > max_chars:
                # Keep first portion of list
                result.data = result.data[:max(max_chars // 100, 1)]
                result.data.append("... [truncated]")
        return result

    def _spill_to_disk(self, result: ActionResult, char_count: int) -> ActionResult:
        """Level 2: Write result data to disk, replace with SpilledResult."""
        trace_dir = self._spill_dir / result.meta.trace_id
        trace_dir.mkdir(parents=True, exist_ok=True)

        file_path = trace_dir / f"{result.meta.trace_id}.json"
        file_path.write_text(result.to_json(), encoding="utf-8")

        preview = result.to_json()[: self._config.preview_length]
        original_type = type(result.data).__name__ if result.data else "None"

        result.data = SpilledResult(
            preview=preview,
            file_path=str(file_path),
            original_type=original_type,
            original_size_chars=char_count,
        )
        return result

    def _spill_largest_results(self) -> None:
        """Level 3: Spill the largest results until within budget."""
        sorted_results = sorted(self._results, key=lambda r: r[1], reverse=True)
        remaining: list[tuple[str, int, ActionResult]] = []
        for result_id, char_count, result in sorted_results:
            if self._turn_used <= self._config.turn_budget:
                remaining.append((result_id, char_count, result))
                continue
            # C3: actually spill this result to disk
            self._turn_used -= char_count  # remove old size from budget
            spilled = self._spill_to_disk(result, char_count)
            # Track the preview size (what we actually send to LLM), not the full SpilledResult
            new_size = self._config.preview_length
            self._turn_used += new_size
            remaining.append((result_id, new_size, spilled))
        self._results = remaining
