"""GAP-02 data types — Tier enums, cascade records, AX snapshot, vision types."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

class Tier(IntEnum):
    """Interaction tiers in priority order. Lower = cheaper and faster."""
    SELECTOR = 1
    COORDINATE = 2
    VISION = 3


class TierOutcome(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class TierAttempt:
    tier: Tier
    outcome: TierOutcome
    duration_ms: float
    error: str | None = None
    coordinates: tuple[float, float] | None = None


@dataclass(frozen=True)
class CascadeResult:
    action: str
    target: str
    attempts: tuple[TierAttempt, ...]
    succeeded_tier: Tier | None = None
    total_duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# AX snapshot (P1 — agent-browser adoption)
# ---------------------------------------------------------------------------

_INTERACTIVE_ROLES = frozenset({
    "button", "link", "textbox", "combobox", "checkbox",
    "radio", "menuitem", "tab", "slider", "searchbox",
    "spinbutton", "switch", "option", "treeitem",
})


@dataclass
class AXNode:
    ref: str
    role: str
    name: str
    url: str | None = None
    value: str | None = None
    description: str | None = None
    bounds: tuple[float, float, float, float] | None = None  # (x, y, w, h)
    focused: bool = False
    disabled: bool = False
    automation_id: str = ""          # UIA AutomationIdProperty / AX identifier
    compound: Any = None              # Optional CompoundInfo for rich form fields

    @property
    def center(self) -> tuple[float, float] | None:
        if self.bounds:
            return (self.bounds[0] + self.bounds[2] / 2,
                    self.bounds[1] + self.bounds[3] / 2)
        return None

    @property
    def is_interactive(self) -> bool:
        return self.role in _INTERACTIVE_ROLES


@dataclass
class AXSnapshot:
    url: str
    title: str
    nodes: dict[str, AXNode] = field(default_factory=dict)
    captured_at: float = field(default_factory=time.monotonic)
    token_count: int = 0

    def resolve(self, ref: str) -> AXNode | None:
        return self.nodes.get(ref.lstrip("@"))

    def find_by_text(self, text: str) -> list[AXNode]:
        text_lower = text.lower()
        return [n for n in self.nodes.values()
                if n.is_interactive and text_lower in n.name.lower()]

    def find_by_role(self, role: str) -> list[AXNode]:
        return [n for n in self.nodes.values() if n.role == role]

    def to_compact_str(self, *, formatted: bool = True) -> str:
        """Serialize snapshot for LLM consumption.

        Args:
            formatted: If True, use the 4-pass formatter for token efficiency.
                       If False, return raw dump (backward compat).
        """
        if formatted:
            try:
                from deskaoy.cascade.formatter import format_snapshot
                return format_snapshot(self)
            except ImportError:
                pass  # fallback to raw

        # Raw dump (original behavior)
        lines = []
        for _ref, node in sorted(self.nodes.items(), key=lambda x: int(x[0][1:])):
            parts = [f"[{node.ref}]", node.role, f'"{node.name}"']
            if node.url:
                parts.append(f"url={node.url}")
            if node.value:
                parts.append(f"value={node.value}")
            if node.disabled:
                parts.append("[disabled]")
            lines.append(" ".join(parts))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Vision types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VisionRequest:
    screenshot: bytes
    element_description: str
    page_url: str
    viewport_size: tuple[int, int]


@dataclass(frozen=True)
class VisionResponse:
    found: bool
    x: float | None = None
    y: float | None = None
    confidence: float = 0.0
    raw_response: str | None = None
    model: str | None = None
    token_cost: float = 0.0
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Compound form field info (G5)
# ---------------------------------------------------------------------------

@dataclass
class CompoundInfo:
    """Rich metadata for form controls that under-specify their state.

    Extracted from UIA combo boxes, date pickers, file dialogs, etc.
    Included in AXNode.compound so the LLM sees the full option list
    without extra probing steps.
    """
    control: str  # "date", "select", "file", "color"
    format: str | None = None        # "MM/dd/yyyy"
    options: list[str] = field(default_factory=list)  # combobox items
    options_total: int = 0
    current: str | None = None       # current value
    accept: str | None = None        # file filter (.pdf,.docx)
    multiple: bool = False              # multi-select / multi-file
