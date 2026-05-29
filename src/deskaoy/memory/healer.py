"""Self-healing anchor recovery.

When a cached selector or anchor breaks, this module tries alternative
strategies to re-locate the target element using the stored evidence.

Healing strategies (in priority order):
  1. AX role + text match — find by role and exact/partial name
  2. Visual fingerprint — compare perceptual hash of element crop
  3. OCR text search — find element containing remembered text
  4. Nearby text anchor — find known nearby text, then look for target nearby
  5. BBox proximity — use remembered normalized position as hint
"""

from __future__ import annotations

import logging

from deskaoy.cascade.types import AXSnapshot
from deskaoy.memory.fingerprint import fingerprint_distance
from deskaoy.memory.matching import match_ax_node
from deskaoy.memory.types import (
    AnchorMatch,
    DurableTarget,
    HealStrategy,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Healing result
# ---------------------------------------------------------------------------


class HealResult:
    """Outcome of a healing attempt."""

    def __init__(
        self,
        success: bool,
        match: AnchorMatch | None = None,
        strategies_tried: list[str] | None = None,
        duration_ms: float = 0.0,
    ) -> None:
        self.success = success
        self.match = match
        self.strategies_tried = strategies_tried or []
        self.duration_ms = duration_ms

    def __repr__(self) -> str:
        if self.success:
            return f"HealResult(success=True, strategy={self.match.strategy if self.match else None})"
        return f"HealResult(success=False, tried={self.strategies_tried})"


# ---------------------------------------------------------------------------
# Self-healer
# ---------------------------------------------------------------------------


class SelfHealer:
    """Attempts to recover broken anchors using stored evidence.

    Each strategy returns an AnchorMatch or None. Strategies are tried
    in order of expected reliability. The first successful match wins.
    """

    def __init__(
        self,
        *,
        fingerprint_threshold: float = 0.15,
        nearby_threshold: float = 200.0,
    ) -> None:
        self._fp_threshold = fingerprint_threshold
        self._nearby_threshold = nearby_threshold

    async def heal(
        self,
        target: DurableTarget,
        snapshot: AXSnapshot | None = None,
        *,
        current_screenshot: bytes | None = None,
        current_detections: list | None = None,
        viewport_size: tuple[int, int] = (0, 0),
    ) -> HealResult:
        """Try all healing strategies to recover a broken anchor.

        Args:
            target: The DurableTarget whose anchor broke.
            snapshot: Current AX snapshot (for structural matching).
            current_screenshot: Current screenshot bytes (for visual matching).
            current_detections: Current frame detections (for OCR/proximity).
            viewport_size: (width, height) of the current viewport.

        Returns:
            HealResult with the best match found, or failure.
        """
        import time as _time
        start = _time.monotonic()
        strategies_tried: list[str] = []

        # Strategy 1: AX role + text match
        if snapshot is not None:
            match = match_ax_node(target, snapshot)
            if match and match.confidence >= 0.5:
                elapsed = (_time.monotonic() - start) * 1000
                return HealResult(
                    success=True,
                    match=match,
                    strategies_tried=[HealStrategy.AX_ROLE_TEXT.value],
                    duration_ms=elapsed,
                )
            strategies_tried.append(HealStrategy.AX_ROLE_TEXT.value)

        # Strategy 2: Visual fingerprint comparison
        if (
            current_screenshot
            and target.visual_fingerprint
            and target.bbox_normalized
            and viewport_size[0] > 0
        ):
            match = self._heal_visual(
                target, current_screenshot, viewport_size
            )
            if match:
                elapsed = (_time.monotonic() - start) * 1000
                strategies_tried.append(HealStrategy.VISUAL_FINGERPRINT.value)
                return HealResult(
                    success=True,
                    match=match,
                    strategies_tried=strategies_tried,
                    duration_ms=elapsed,
                )
            strategies_tried.append(HealStrategy.VISUAL_FINGERPRINT.value)

        # Strategy 3: OCR text search
        if current_detections and target.ocr_text:
            match = self._heal_ocr(target, current_detections)
            if match:
                elapsed = (_time.monotonic() - start) * 1000
                strategies_tried.append(HealStrategy.OCR_SEARCH.value)
                return HealResult(
                    success=True,
                    match=match,
                    strategies_tried=strategies_tried,
                    duration_ms=elapsed,
                )
            strategies_tried.append(HealStrategy.OCR_SEARCH.value)

        # Strategy 4: Nearby text anchor
        if snapshot is not None and target.nearby_text:
            match = self._heal_nearby_text(target, snapshot)
            if match:
                elapsed = (_time.monotonic() - start) * 1000
                strategies_tried.append(HealStrategy.NEARBY_TEXT_ANCHOR.value)
                return HealResult(
                    success=True,
                    match=match,
                    strategies_tried=strategies_tried,
                    duration_ms=elapsed,
                )
            strategies_tried.append(HealStrategy.NEARBY_TEXT_ANCHOR.value)

        # Strategy 5: BBox proximity hint
        if (
            target.bbox_normalized
            and viewport_size[0] > 0
            and current_detections
        ):
            match = self._heal_bbox_proximity(target, current_detections, viewport_size)
            if match:
                elapsed = (_time.monotonic() - start) * 1000
                strategies_tried.append(HealStrategy.BBOX_PROXIMITY.value)
                return HealResult(
                    success=True,
                    match=match,
                    strategies_tried=strategies_tried,
                    duration_ms=elapsed,
                )
            strategies_tried.append(HealStrategy.BBOX_PROXIMITY.value)

        elapsed = (_time.monotonic() - start) * 1000
        return HealResult(
            success=False,
            strategies_tried=strategies_tried,
            duration_ms=elapsed,
        )

    # -- Strategy implementations --

    def _heal_visual(
        self,
        target: DurableTarget,
        screenshot: bytes,
        viewport_size: tuple[int, int],
    ) -> AnchorMatch | None:
        """Try visual fingerprint match at the remembered location."""
        from deskaoy.memory.fingerprint import crop_fingerprint

        if not target.bbox_normalized:
            return None

        vx, vy = viewport_size[0], viewport_size[1]
        x_pct, y_pct, w_pct, h_pct = target.bbox_normalized

        pixel_bbox = (
            x_pct * vx,
            y_pct * vy,
            (x_pct + w_pct) * vx,
            (y_pct + h_pct) * vy,
        )

        current_fp = crop_fingerprint(screenshot, pixel_bbox, viewport_size)
        if current_fp is None:
            return None

        distance = fingerprint_distance(target.visual_fingerprint, current_fp)
        if distance < self._fp_threshold:
            return AnchorMatch(
                target_id=target.target_id,
                anchor_kind="visual_fingerprint",
                anchor_value=current_fp,
                confidence=1.0 - distance,
                strategy=HealStrategy.VISUAL_FINGERPRINT,
                healed=True,
            )
        return None

    def _heal_ocr(
        self,
        target: DurableTarget,
        detections: list,
    ) -> AnchorMatch | None:
        """Search current detections for the remembered OCR text."""
        target_text = (target.ocr_text or "").strip().lower()
        if not target_text:
            return None

        for det in detections:
            det_text = ""
            if hasattr(det, "text") and det.text:
                det_text = det.text
            elif hasattr(det, "label") and det.label:
                det_text = det.label

            if target_text in det_text.strip().lower():
                return AnchorMatch(
                    target_id=target.target_id,
                    anchor_kind="ocr_text",
                    anchor_value=det_text,
                    confidence=0.70,
                    strategy=HealStrategy.OCR_SEARCH,
                    healed=True,
                )
        return None

    def _heal_nearby_text(
        self,
        target: DurableTarget,
        snapshot: AXSnapshot,
    ) -> AnchorMatch | None:
        """Find nearby text anchors, then look for target role nearby."""
        if not target.nearby_text or not snapshot.nodes:
            return None

        expected_role = target.uia_control_type or target.ax_node_role
        if not expected_role:
            return None

        for nearby_text in target.nearby_text:
            anchor_nodes = snapshot.find_by_text(nearby_text)
            if not anchor_nodes:
                continue

            anchor_node = anchor_nodes[0]
            candidates = snapshot.find_by_role(expected_role)
            for candidate in candidates:
                if _nodes_near(anchor_node, candidate, self._nearby_threshold):
                    return AnchorMatch(
                        target_id=target.target_id,
                        anchor_kind="nearby_text",
                        anchor_value=candidate.ref,
                        confidence=0.60,
                        strategy=HealStrategy.NEARBY_TEXT_ANCHOR,
                        healed=True,
                    )
        return None

    def _heal_bbox_proximity(
        self,
        target: DurableTarget,
        detections: list,
        viewport_size: tuple[int, int],
    ) -> AnchorMatch | None:
        """Find the closest detection to the remembered bbox."""
        if not target.bbox_normalized:
            return None

        vx = viewport_size[0]
        vy = viewport_size[1]
        x_pct, y_pct, w_pct, h_pct = target.bbox_normalized
        target_cx = (x_pct + w_pct / 2) * vx
        target_cy = (y_pct + h_pct / 2) * vy

        best_dist = float("inf")
        best_det = None

        for det in detections:
            if not hasattr(det, "bbox") or det.bbox is None:
                continue
            cx, cy = det.bbox.center
            dist = ((cx - target_cx) ** 2 + (cy - target_cy) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_det = det

        if best_det and best_dist < 100:  # within 100px
            return AnchorMatch(
                target_id=target.target_id,
                anchor_kind="bbox_normalized",
                anchor_value=f"{best_dist:.0f}px",
                confidence=max(0.3, 0.6 - best_dist / 500),
                strategy=HealStrategy.BBOX_PROXIMITY,
                healed=True,
            )
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _nodes_near(a: object, b: object, threshold: float) -> bool:
    """Check if two nodes are physically close."""
    a_bounds = getattr(a, "bounds", None)
    b_bounds = getattr(b, "bounds", None)
    if not a_bounds or not b_bounds:
        return False

    a_cx = a_bounds[0] + a_bounds[2] / 2
    a_cy = a_bounds[1] + a_bounds[3] / 2
    b_cx = b_bounds[0] + b_bounds[2] / 2
    b_cy = b_bounds[1] + b_bounds[3] / 2

    dist = ((a_cx - b_cx) ** 2 + (a_cy - b_cy) ** 2) ** 0.5
    return dist < threshold
