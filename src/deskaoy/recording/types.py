"""Recording types — dataclasses for session recording.

Pattern source: SUPER-BROWSER recording/types.py
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StepRecord:
    """A single recorded step in an automation session."""
    step_index: int
    action: str
    target: str = ""
    value: str = ""
    tier_used: str = "uia"
    succeeded: bool = True
    error_message: str = ""
    screenshot_path: str = ""
    timestamp: float = field(default_factory=time.monotonic)
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecordingSession:
    """Complete recording of an automation session."""
    session_id: str = ""
    instruction: str = ""
    started_at: float = field(default_factory=time.monotonic)
    stopped_at: float = 0.0
    steps: list[StepRecord] = field(default_factory=list)
    final_state: str = "in_progress"  # in_progress | completed | failed | aborted

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def success_rate(self) -> float:
        if not self.steps:
            return 0.0
        return sum(1 for s in self.steps if s.succeeded) / len(self.steps)

    @property
    def duration_s(self) -> float:
        if self.stopped_at <= 0:
            return 0.0
        return self.stopped_at - self.started_at


# Sensitive keys to filter from recorded params
_SENSITIVE_KEYS = frozenset({
    "password", "secret", "token", "api_key", "credential",
    "auth", "private_key", "access_key",
})


def _filter_sensitive(params: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive values from recorded parameters."""
    filtered = {}
    for k, v in params.items():
        if any(s in k.lower() for s in _SENSITIVE_KEYS):
            filtered[k] = "[REDACTED]"
        else:
            filtered[k] = v
    return filtered
