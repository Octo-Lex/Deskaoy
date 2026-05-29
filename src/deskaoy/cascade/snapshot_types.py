"""Snapshot state types — Peekaboo-inspired persistent UI element snapshots.

Data models for persisting AXSnapshot state to disk with stable element IDs.
Enables multi-command workflows where see → click → type chains resolve
elements by ID rather than by re-detection.

Storage: ~/.deskaoy/snapshots/<uuid>/snapshot.json
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Role → prefix mapping for deterministic element IDs
# ---------------------------------------------------------------------------

# Exported for uia_walker element ID resolution (BATCH-25)
ROLE_PREFIXES: dict[str, str] = {
    "textbox": "T",
    "text": "T",
    "edit": "T",
    "searchbox": "T",
    "spinbutton": "T",
    "button": "B",
    "link": "B",
    "menuitem": "M",
    "menu": "M",
    "menubar": "M",
    "checkbox": "C",
    "radio": "C",
    "switch": "C",
    "slider": "S",
    "scrollbar": "S",
}
# Private alias for backward compat with existing code
_ROLE_PREFIXES = ROLE_PREFIXES

_PREFIX_RE = re.compile(r"^[ETBMCS]\d+$")

# Role aliases — map UIA roles to canonical prefix groups
# Exported for uia_walker element ID resolution (BATCH-25)
ROLE_ALIASES: dict[str, str] = {
    "edit": "textbox",
    "searchbox": "textbox",
    "spinbutton": "textbox",
    "link": "button",
    "menu": "menuitem",
    "menubar": "menuitem",
    "radio": "checkbox",
    "switch": "checkbox",
    "scrollbar": "slider",
}
# Private alias for backward compat with existing code
_ROLE_ALIASES = ROLE_ALIASES


def get_role_prefix(role: str) -> str:
    """Return the element-ID prefix for a given accessibility role.

    Falls back to ``E`` (generic) for unknown roles.
    """
    canonical = _ROLE_ALIASES.get(role, role)
    return _ROLE_PREFIXES.get(canonical, "E")


def assign_element_ids(elements: list[dict]) -> list[str]:
    """Assign deterministic element IDs to a list of element dicts.

    Each element must have a ``role`` key. IDs use role-based prefixes
    (E, T, B, M, C, S) followed by a sequential counter within that
    prefix group. Assignment order follows the input list order (i.e.
    depth-first AX tree traversal order).

    Returns a list of element_id strings in the same order as the input.
    """
    counters: dict[str, int] = {}
    ids: list[str] = []
    for elem in elements:
        role = elem.get("role", "")
        prefix = get_role_prefix(role)
        counters[prefix] = counters.get(prefix, 0) + 1
        ids.append(f"{prefix}{counters[prefix]}")
    return ids


def validate_element_id(element_id: str) -> bool:
    """Check if an element ID matches the expected format."""
    return bool(_PREFIX_RE.match(element_id))


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SnapshotElement:
    """A single UI element within a persisted snapshot.

    Attributes:
        element_id: Stable identifier like E1, T2, B3 — deterministic for the
                    same snapshot across loads (HB-02).
        role:       Accessibility role (button, textbox, window, etc.)
        name:       Element accessible name / label.
        bounds:     Dict with x, y, width, height keys.
        actionable: Whether the element can be interacted with.
        value:      Current value (for text inputs, etc.)
        description: Extended description if available.
    """

    element_id: str
    role: str
    name: str | None = None
    bounds: dict | None = None
    actionable: bool = False
    value: str | None = None
    description: str | None = None

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return {
            "element_id": self.element_id,
            "role": self.role,
            "name": self.name,
            "bounds": self.bounds,
            "actionable": self.actionable,
            "value": self.value,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SnapshotElement:
        """Deserialize from a dict."""
        return cls(
            element_id=data["element_id"],
            role=data["role"],
            name=data.get("name"),
            bounds=data.get("bounds"),
            actionable=data.get("actionable", False),
            value=data.get("value"),
            description=data.get("description"),
        )


@dataclass
class SnapshotRecord:
    """A persisted snapshot of the UI element tree.

    Stored as ``~/.deskaoy/snapshots/<snapshot_id>/snapshot.json``.

    HB-03: No credentials, API keys, or environment variables are stored.
    Only elements, window metadata, capture timestamp, and snapshot ID.
    """

    snapshot_id: str
    created_at: str  # ISO-8601
    application: str | None = None
    window_title: str | None = None
    window_bounds: dict | None = None
    bundle_id: str | None = None
    pid: int | None = None
    platform: str = "windows"
    elements: list[SnapshotElement] = field(default_factory=list)
    screenshot_path: Path | None = None

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict for snapshot.json."""
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "application": self.application,
            "window_title": self.window_title,
            "window_bounds": self.window_bounds,
            "bundle_id": self.bundle_id,
            "pid": self.pid,
            "platform": self.platform,
            "elements": [e.to_dict() for e in self.elements],
        }

    @classmethod
    def from_dict(cls, data: dict, *, screenshot_path: Path | None = None) -> SnapshotRecord:
        """Deserialize from a dict (as read from snapshot.json)."""
        elements = [SnapshotElement.from_dict(e) for e in data.get("elements", [])]
        return cls(
            snapshot_id=data["snapshot_id"],
            created_at=data["created_at"],
            application=data.get("application"),
            window_title=data.get("window_title"),
            window_bounds=data.get("window_bounds"),
            bundle_id=data.get("bundle_id"),
            pid=data.get("pid"),
            platform=data.get("platform", "windows"),
            elements=elements,
            screenshot_path=screenshot_path,
        )


@dataclass
class SnapshotInfo:
    """Summary info for listing snapshots (no element data)."""

    snapshot_id: str
    created_at: str
    application: str | None = None
    element_count: int = 0
    has_screenshot: bool = False


@dataclass
class StaleResult:
    """Result of a stale-snapshot check.

    ``is_stale`` is True if the snapshot no longer reflects the current
    window state. ``reason`` is empty string when fresh, or one of:
    ``window_moved``, ``window_resized``, ``window_closed``,
    ``title_changed``, ``not_found``.
    """

    is_stale: bool
    reason: str = ""
