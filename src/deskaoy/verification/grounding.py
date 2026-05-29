"""Post-action grounding verification — LangExtract-inspired 4-tier alignment.

After every action, verifies the target element still exists using a
4-tier cascade modeled on LangExtract's extraction alignment:

  1. STRUCTURAL — AXNode ref found with same properties (0.95+ confidence)
  2. VISUAL     — Same bounding box still present (0.80+)
  3. TEXT       — Same text found somewhere in snapshot (0.60+)
  4. UNVERIFIED — No post-check possible (0.0)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class GroundingTier(StrEnum):
    """4-tier post-action verification, inspired by LangExtract AlignmentStatus."""
    STRUCTURAL = "structural"  # AXNode ref found, properties match (0.95+)
    VISUAL = "visual"          # Same bounding box present (0.80+)
    TEXT = "text"              # Same text found in snapshot (0.60+)
    UNVERIFIED = "unverified"  # No verification possible (0.0)


TIER_CONFIDENCE = {
    GroundingTier.STRUCTURAL: 0.95,
    GroundingTier.VISUAL: 0.80,
    GroundingTier.TEXT: 0.60,
    GroundingTier.UNVERIFIED: 0.0,
}


@dataclass
class ActionGrounding:
    """Verification that an action's target still exists post-execution.

    Modeled after LangExtract's ``Extraction.char_interval`` +
    ``AlignmentStatus`` — every action result carries grounding evidence.
    """

    tier: GroundingTier
    confidence: float
    target_ref: str = ""
    target_text: str = ""
    target_bounds: tuple[float, float, float, float] | None = None
    still_exists: bool = True
    properties_changed: list[str] = field(default_factory=list)
    verification_method: str = ""  # "ax_tree" | "visual_diff" | "ocr" | "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": str(self.tier),
            "confidence": self.confidence,
            "target_ref": self.target_ref,
            "target_text": self.target_text,
            "target_bounds": list(self.target_bounds) if self.target_bounds else None,
            "still_exists": self.still_exists,
            "properties_changed": self.properties_changed,
            "verification_method": self.verification_method,
        }


# ---------------------------------------------------------------------------
# Grounding verifier
# ---------------------------------------------------------------------------

def verify_grounding(
    *,
    target_ref: str = "",
    target_text: str = "",
    target_bounds: tuple[float, float, float, float] | None = None,
    post_snapshot: Any = None,
) -> ActionGrounding:
    """Run the 4-tier grounding cascade against a post-action snapshot.

    Args:
        target_ref: AXNode ref that was targeted (e.g. "e42").
        target_text: Text/name of the target element.
        target_bounds: (x, y, w, h) of the target element.
        post_snapshot: AXSnapshot taken after the action.

    Returns:
        ActionGrounding with the highest-confidence tier achieved.
    """
    if post_snapshot is None:
        return ActionGrounding(
            tier=GroundingTier.UNVERIFIED,
            confidence=0.0,
            target_ref=target_ref,
            target_text=target_text,
            target_bounds=target_bounds,
            still_exists=False,
            verification_method="none",
        )

    # --- Tier 1: STRUCTURAL (exact ref match) ---
    if target_ref:
        node = post_snapshot.resolve(target_ref)
        if node is not None:
            changed = _detect_property_changes(node, target_text, target_bounds)
            return ActionGrounding(
                tier=GroundingTier.STRUCTURAL,
                confidence=TIER_CONFIDENCE[GroundingTier.STRUCTURAL],
                target_ref=target_ref,
                target_text=target_text,
                target_bounds=target_bounds,
                still_exists=True,
                properties_changed=changed,
                verification_method="ax_tree",
            )

    # --- Tier 2: VISUAL (same bounding box) ---
    if target_bounds:
        match = _find_by_bounds(post_snapshot, target_bounds)
        if match is not None:
            return ActionGrounding(
                tier=GroundingTier.VISUAL,
                confidence=TIER_CONFIDENCE[GroundingTier.VISUAL],
                target_ref=target_ref,
                target_text=target_text,
                target_bounds=target_bounds,
                still_exists=True,
                verification_method="visual_diff",
            )

    # --- Tier 3: TEXT (same text found anywhere) ---
    if target_text:
        matches = post_snapshot.find_by_text(target_text)
        if matches:
            return ActionGrounding(
                tier=GroundingTier.TEXT,
                confidence=TIER_CONFIDENCE[GroundingTier.TEXT],
                target_ref=target_ref,
                target_text=target_text,
                target_bounds=target_bounds,
                still_exists=True,
                verification_method="ocr",
            )

    # --- Tier 4: UNVERIFIED ---
    return ActionGrounding(
        tier=GroundingTier.UNVERIFIED,
        confidence=0.0,
        target_ref=target_ref,
        target_text=target_text,
        target_bounds=target_bounds,
        still_exists=False,
        verification_method="none",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _detect_property_changes(
    node: Any,
    expected_text: str,
    expected_bounds: tuple[float, float, float, float] | None,
) -> list[str]:
    """Detect which properties changed on the node vs expectations."""
    changed: list[str] = []
    if expected_text and node.name != expected_text:
        changed.append("name")
    if expected_bounds and node.bounds:
        # Compare bounds with small tolerance for rounding
        for _i, (actual, expected) in enumerate(zip(node.bounds, expected_bounds, strict=False)):
            if abs(actual - expected) > 1.0:
                changed.append("bounds")
                break
    if node.disabled:
        changed.append("disabled")
    return changed


def _find_by_bounds(
    snapshot: Any,
    target_bounds: tuple[float, float, float, float],
    tolerance: float = 5.0,
) -> Any:
    """Find a node in the snapshot with matching bounding box."""
    tx, ty, tw, th = target_bounds
    for node in snapshot.nodes.values():
        if node.bounds is None:
            continue
        nx, ny, nw, nh = node.bounds
        if (
            abs(nx - tx) <= tolerance
            and abs(ny - ty) <= tolerance
            and abs(nw - tw) <= tolerance
            and abs(nh - th) <= tolerance
        ):
            return node
    return None
