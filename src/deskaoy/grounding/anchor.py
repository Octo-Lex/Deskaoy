"""Stable anchor IDs for cross-frame element tracking.

An anchor is a hash(role + label + normalized_position) that identifies the
same UI element across consecutive screenshots. Survives minor position shifts
(threshold-based, not exact match).
"""

from __future__ import annotations

import hashlib

from deskaoy.grounding.types import FusedElement

# Position quantization — snap to grid so minor shifts produce the same anchor.
_POSITION_GRID = 20  # pixels

# Maximum normalized distance for two anchors to be considered "same element".
_MAX_ANCHOR_DRIFT = 0.02  # 2% of viewport


def compute_anchor(
    element: FusedElement,
    viewport_w: int,
    viewport_h: int,
) -> str:
    """Compute a stable anchor ID for a FusedElement.

    The anchor is derived from:
      - role (button, input, etc.)
      - label text (lowercased, stripped)
      - quantized center position (snapped to a grid)

    Same element at roughly the same position with the same role/label
    gets the same anchor. Scrolling changes the position → different anchor.
    """
    cx, cy = element.bbox.center
    # Quantize position to reduce jitter from minor pixel shifts
    qx = round(cx / _POSITION_GRID) * _POSITION_GRID
    qy = round(cy / _POSITION_GRID) * _POSITION_GRID
    # Normalize to viewport
    nx = round(qx / viewport_w, 4)
    ny = round(qy / viewport_h, 4)

    label = (element.label or "").strip().lower()
    raw = f"{element.role.value}:{label}:{nx},{ny}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def anchors_match(a: str, b: str) -> bool:
    """Check if two anchor IDs match (exact string match)."""
    return a == b


def build_anchor_map(
    elements: list[FusedElement],
    viewport_w: int,
    viewport_h: int,
) -> dict[str, FusedElement]:
    """Build a map of anchor_id → element for a frame."""
    result: dict[str, FusedElement] = {}
    for el in elements:
        aid = compute_anchor(el, viewport_w, viewport_h)
        # Assign the anchor_id to a new FusedElement (frozen dataclass → replace)
        anchored = FusedElement(
            bbox=el.bbox,
            role=el.role,
            label=el.label,
            confidence=el.confidence,
            source=el.source,
            sources=el.sources,
            text=el.text,
            anchor_id=aid,
            metadata=el.metadata,
        )
        # First occurrence wins (higher-confidence elements come first in fusion)
        if aid not in result:
            result[aid] = anchored
    return result
