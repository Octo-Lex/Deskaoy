"""Cross-frame element tracking via stable anchors.

Compares two frames of FusedElements and classifies each element as
stable (present in both), appeared (new), or disappeared (gone).
"""

from __future__ import annotations

from deskaoy.grounding.anchor import build_anchor_map
from deskaoy.grounding.types import FrameDelta, FusedElement


def track_frames(
    prev: list[FusedElement],
    curr: list[FusedElement],
    viewport_w: int,
    viewport_h: int,
) -> FrameDelta:
    """Compare two frames and return element-level delta.

    Uses anchor IDs (role + label + quantized position) for matching.
    Elements with the same anchor in both frames are "stable".
    """
    prev_map = build_anchor_map(prev, viewport_w, viewport_h)
    curr_map = build_anchor_map(curr, viewport_w, viewport_h)

    prev_ids = set(prev_map.keys())
    curr_ids = set(curr_map.keys())

    stable_ids = prev_ids & curr_ids
    appeared_ids = curr_ids - prev_ids
    disappeared_ids = prev_ids - curr_ids

    return FrameDelta(
        stable=[curr_map[aid] for aid in sorted(stable_ids)],
        appeared=[curr_map[aid] for aid in sorted(appeared_ids)],
        disappeared=[prev_map[aid] for aid in sorted(disappeared_ids)],
    )
