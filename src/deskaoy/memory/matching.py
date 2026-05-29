"""Anchor matching and scoring for action memory retrieval.

Given a DurableTarget and optionally the current AX snapshot,
score and rank available anchors by likelihood of success.
"""

from __future__ import annotations

import logging

from deskaoy.cascade.types import AXNode, AXSnapshot
from deskaoy.memory.types import (
    AnchorKind,
    AnchorMatch,
    DurableTarget,
    HealStrategy,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------

# Base scores for each anchor kind (higher = more reliable)
_ANCHOR_BASE_SCORES: dict[AnchorKind, float] = {
    AnchorKind.SELECTOR: 0.95,
    AnchorKind.AX_PATH: 0.90,
    AnchorKind.UIA_AUTOMATION_ID: 0.90,
    AnchorKind.UIA_NAME: 0.80,
    AnchorKind.UIA_CLASS: 0.70,
    AnchorKind.VISUAL_FINGERPRINT: 0.75,
    AnchorKind.OCR_TEXT: 0.70,
    AnchorKind.NEARBY_TEXT: 0.60,
    AnchorKind.BBOX_NORMALIZED: 0.50,
    AnchorKind.COORDINATE: 0.40,
}

# Reliability multiplier thresholds
_HIGH_RELIABILITY = 0.8
_LOW_RELIABILITY = 0.3


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_target(target: DurableTarget) -> float:
    """Compute an overall confidence score for a DurableTarget.

    Factors in:
      - Base anchor score (best available anchor)
      - Reliability (success / total)
      - Recency bonus
      - Anchor diversity bonus
    """
    if not target.available_anchors:
        return 0.0

    # Best anchor base score
    best_anchor = target.best_anchor or target.available_anchors[0]
    base = _ANCHOR_BASE_SCORES.get(best_anchor, 0.5)

    # Reliability modifier
    reliability = target.reliability
    if reliability >= _HIGH_RELIABILITY:
        reliability_mod = 1.0
    elif reliability <= _LOW_RELIABILITY:
        reliability_mod = 0.5
    else:
        reliability_mod = 0.5 + (reliability - _LOW_RELIABILITY) / (
            _HIGH_RELIABILITY - _LOW_RELIABILITY
        ) * 0.5

    # Anchor diversity bonus (more anchors = more fallback options)
    diversity_bonus = min(0.1, len(target.available_anchors) * 0.02)

    # Staleness penalty
    staleness_penalty = 0.0
    if target.is_stale:
        staleness_penalty = 0.3

    return max(0.0, min(1.0, base * reliability_mod + diversity_bonus - staleness_penalty))


def rank_anchors(target: DurableTarget) -> list[AnchorMatch]:
    """Rank all available anchors for a target by expected success.

    Returns anchors in priority order — try these in sequence.
    """
    scored: list[tuple[float, AnchorKind]] = []

    for anchor_kind in target.available_anchors:
        score = _score_anchor(target, anchor_kind)
        scored.append((score, anchor_kind))

    scored.sort(key=lambda x: x[0], reverse=True)

    return [
        AnchorMatch(
            target_id=target.target_id,
            anchor_kind=kind,
            anchor_value=_get_anchor_value(target, kind),
            confidence=score,
        )
        for score, kind in scored
    ]


def match_ax_node(
    target: DurableTarget,
    snapshot: AXSnapshot,
) -> AnchorMatch | None:
    """Try to find a matching AX node in the current snapshot.

    Healing strategies:
      1. Exact name + role match
      2. Partial text match in name
      3. Nearby text anchor (find known nearby text, look for target role nearby)
    """
    if not snapshot.nodes:
        return None

    # Strategy 1: Exact name + role match
    if target.uia_name:
        expected_name = target.uia_name
        expected_role = target.uia_control_type

        for node in snapshot.nodes.values():
            if not node.is_interactive:
                continue
            if expected_role and node.role != expected_role:
                continue
            if node.name and expected_name and node.name.strip().lower() == expected_name.strip().lower():
                return AnchorMatch(
                    target_id=target.target_id,
                    anchor_kind=AnchorKind.UIA_NAME,
                    anchor_value=node.ref,
                    confidence=0.85,
                    strategy=HealStrategy.AX_ROLE_TEXT,
                    healed=True,
                )

    # Strategy 2: Partial text match
    search_text = target.ocr_text or target.uia_name or ""
    if search_text:
        matches = snapshot.find_by_text(search_text)
        if matches:
            best = matches[0]
            return AnchorMatch(
                target_id=target.target_id,
                anchor_kind=AnchorKind.AX_PATH,
                anchor_value=best.ref,
                confidence=0.70,
                strategy=HealStrategy.AX_ROLE_TEXT,
                healed=True,
            )

    # Strategy 3: Nearby text anchor
    if target.nearby_text:
        for nearby in target.nearby_text:
            nearby_nodes = snapshot.find_by_text(nearby)
            if nearby_nodes:
                anchor_node = nearby_nodes[0]
                # Look for an interactive element near this anchor
                expected_role = target.uia_control_type
                if expected_role:
                    candidates = snapshot.find_by_role(expected_role)
                    for candidate in candidates:
                        if _nodes_near(anchor_node, candidate):
                            return AnchorMatch(
                                target_id=target.target_id,
                                anchor_kind=AnchorKind.NEARBY_TEXT,
                                anchor_value=candidate.ref,
                                confidence=0.60,
                                strategy=HealStrategy.NEARBY_TEXT_ANCHOR,
                                healed=True,
                            )

    return None


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _score_anchor(target: DurableTarget, kind: AnchorKind) -> float:
    """Score a single anchor for a target."""
    base = _ANCHOR_BASE_SCORES.get(kind, 0.5)

    # Boost if this anchor was the one that last succeeded
    if target.successful_tier:
        last_record = None
        for record in reversed(target.tier_history):
            if record.outcome in ("success", "healed"):
                last_record = record
                break

        if last_record and last_record.anchor_used == kind.value:
            base = min(1.0, base + 0.05)

    # Scale by target reliability
    return base * max(0.3, target.reliability)


def _get_anchor_value(target: DurableTarget, kind: AnchorKind) -> str:
    """Get the stored value for an anchor kind."""
    mapping: dict[AnchorKind, str | None] = {
        AnchorKind.SELECTOR: target.selector,
        AnchorKind.AX_PATH: target.ax_path,
        AnchorKind.UIA_AUTOMATION_ID: target.uia_automation_id,
        AnchorKind.UIA_NAME: target.uia_name,
        AnchorKind.UIA_CLASS: target.uia_class,
        AnchorKind.VISUAL_FINGERPRINT: target.visual_fingerprint,
        AnchorKind.OCR_TEXT: target.ocr_text,
        AnchorKind.BBOX_NORMALIZED: (
            f"{target.bbox_normalized[0]:.3f},{target.bbox_normalized[1]:.3f},"
            f"{target.bbox_normalized[2]:.3f},{target.bbox_normalized[3]:.3f}"
            if target.bbox_normalized
            else None
        ),
        AnchorKind.NEARBY_TEXT: (
            "|".join(target.nearby_text) if target.nearby_text else None
        ),
        AnchorKind.COORDINATE: None,
    }
    return mapping.get(kind) or ""


def _nodes_near(a: AXNode, b: AXNode, *, threshold: float = 200.0) -> bool:
    """Check if two AX nodes are physically near each other."""
    if not a.bounds or not b.bounds:
        return False

    a_cx = a.bounds[0] + a.bounds[2] / 2
    a_cy = a.bounds[1] + a.bounds[3] / 2
    b_cx = b.bounds[0] + b.bounds[2] / 2
    b_cy = b.bounds[1] + b.bounds[3] / 2

    dist = ((a_cx - b_cx) ** 2 + (a_cy - b_cy) ** 2) ** 0.5
    return dist < threshold
